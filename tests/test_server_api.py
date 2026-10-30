"""Exercises the real HTTP adapter against a local aiohttp server, without a GPU."""
import importlib
from pathlib import Path
import sys
import types
import unittest
import uuid
from unittest.mock import patch

from aiohttp import web
from aiohttp.test_utils import TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class ServerAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        try:
            self.api = importlib.import_module('server_api')
        except ImportError:
            self.fail('server_api implementation is not present yet')

    async def test_submit_uses_preallocated_uuid_and_parses_history_and_queue(self):
        prompt_id = str(uuid.uuid4())
        seen = []
        async def post_prompt(request):
            body = await request.json()
            seen.append(body)
            return web.json_response({'prompt_id': body['prompt_id'], 'number': 1, 'node_errors': {}})
        async def history(request):
            return web.json_response({prompt_id: {'status': {'status_str': 'error', 'completed': False}, 'outputs': {}}})
        async def queue(request):
            return web.json_response({'queue_running': [[1, prompt_id, {}, {}, []]], 'queue_pending': []})
        app = web.Application()
        app.router.add_post('/prompt', post_prompt)
        app.router.add_get('/history/{id}', history)
        app.router.add_get('/queue', queue)
        async with TestServer(app) as server:
            client = self.api.ComfyClient(str(server.make_url('')).rstrip('/'))
            result = await client.submit({'1': {'class_type': 'Example', 'inputs': {}}}, prompt_id)
            self.assertEqual(result['prompt_id'], prompt_id)
            self.assertEqual(seen, [{'prompt': {'1': {'class_type': 'Example', 'inputs': {}}}, 'prompt_id': prompt_id}])
            self.assertEqual((await client.history(prompt_id))[prompt_id]['status']['status_str'], 'error')
            self.assertEqual(await client.queue_ids(), {prompt_id})

    async def test_validation_rejection_is_definitive_and_retains_node_error_details(self):
        async def reject(request):
            return web.json_response({'error': {'message': 'Bad workflow'}, 'node_errors': {'7': {'errors': [{'message': 'Model not found'}]}}}, status=400)
        app = web.Application()
        app.router.add_post('/prompt', reject)
        async with TestServer(app) as server:
            client = self.api.ComfyClient(str(server.make_url('')).rstrip('/'))
            with self.assertRaises(self.api.ComfyAPIError) as failure:
                await client.submit({}, str(uuid.uuid4()))
            self.assertTrue(failure.exception.definitive)
            self.assertIn('Bad workflow', str(failure.exception))
            self.assertIn('Model not found', str(failure.exception))

    async def test_redirect_is_reported_without_contacting_target(self):
        contacted = []
        async def redirect(request):
            raise web.HTTPFound('/unexpected')
        async def target(request):
            contacted.append(True)
            return web.json_response({'prompt_id': 'unexpected'})
        app = web.Application()
        app.router.add_post('/prompt', redirect)
        app.router.add_get('/unexpected', target)
        async with TestServer(app) as server:
            client = self.api.ComfyClient(str(server.make_url('')).rstrip('/'))
            with self.assertRaises(self.api.ComfyAPIError):
                await client.submit({}, str(uuid.uuid4()))
            self.assertEqual(contacted, [])

    async def test_server_destination_comes_from_socket_never_host(self):
        transport = types.SimpleNamespace(get_extra_info=lambda key: ('127.0.0.1', 8188) if key == 'sockname' else None)
        request = types.SimpleNamespace(transport=transport, secure=False, headers={'Host': 'attacker.invalid:4444', 'Authorization': 'Bearer ephemeral', 'Cookie': 'session=secret'})
        origin, headers = self.api.connection_context(request)
        self.assertEqual(origin, 'http://127.0.0.1:8188')
        self.assertEqual(headers['Authorization'], 'Bearer ephemeral')
        self.assertNotIn('Host', headers)
        request.transport = types.SimpleNamespace(get_extra_info=lambda key: ('::1', 8188, 0, 0))
        self.assertEqual(self.api.connection_context(request)[0], 'http://[::1]:8188')
        request.transport = None
        with self.assertRaises(ValueError):
            self.api.connection_context(request)

    async def test_register_routes_passes_only_an_explicit_gate_to_manager(self):
        class Routes:
            @staticmethod
            def get(path):
                return lambda handler: handler

            @staticmethod
            def post(path):
                return lambda handler: handler

        class PromptServer:
            routes = Routes()

        observed = {}

        class Manager:
            def __init__(self, root, input_root, client_factory, continuity_gate=None):
                observed['gate'] = continuity_gate

        marker = object()
        with patch('runner.JobManager', Manager):
            self.api.register_routes(PromptServer(), Path('/input'), Path('/output'), continuity_gate=marker)
        self.assertIs(observed['gate'], marker)


if __name__ == '__main__':
    unittest.main()
