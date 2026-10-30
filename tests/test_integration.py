"""CPU integration: real custom routes, runner, HTTP, PNGs and tiny encoded clips.

The video-model worker is a controlled substitute, not a live ComfyUI/GPU test.
"""
import asyncio
import importlib
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest

import aiohttp
from aiohttp import web
from aiohttp.test_utils import TestServer
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is optional for this integration fixture')
class SequenceIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_two_clips_via_public_http_commit_outputs_and_handoff_actual_last_frame(self):
        try:
            server_api = importlib.import_module('server_api')
            image_io = importlib.import_module('image_io')
            importlib.import_module('runner')
        except ImportError:
            self.fail('sequence integration implementation is not present yet')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_root, output_root = root / 'input', root / 'output'
            input_root.mkdir()
            output_root.mkdir()
            Image.new('RGB', (32, 18), 'red').save(input_root / 'first.png')
            Image.new('RGB', (32, 18), 'blue').save(input_root / 'last.png')
            received, history, running, tasks = [], {}, set(), []
            fake_server = types.SimpleNamespace(routes=web.RouteTableDef())
            manager = server_api.register_routes(fake_server, input_root, output_root)

            async def render(prompt, prompt_id):
                values = prompt['1']['inputs']
                try:
                    first = image_io.load_image_array(input_root, values['first_image'])[0]
                    last = image_io.load_image_array(input_root, values['last_image'])[0]
                    image_io.save_endpoints(input_root, output_root / 'alpha_scene_director', values['run_id'], values['clip_id'], first, last, values['frames'])
                    folder = f"alpha_scene_director/{values['run_id']}"
                    filename = values['clip_id'] + '.mp4'
                    video_path = output_root / folder / filename
                    process = await asyncio.create_subprocess_exec(
                        'ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=32x18:r=2',
                        '-frames:v', '3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-y', str(video_path),
                        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    )
                    _, error = await process.communicate()
                    if process.returncode:
                        raise RuntimeError(error.decode())
                    history[prompt_id] = {'prompt': [0, prompt_id, prompt, {}, ['4']],
                        'outputs': {'4': {'images': [{'filename': filename, 'subfolder': folder, 'type': 'output'}]}},
                        'status': {'status_str': 'success', 'completed': True, 'messages': []}}
                except Exception as error:
                    history[prompt_id] = {'outputs': {}, 'status': {'status_str': 'error', 'completed': False, 'messages': [['execution_error', {'exception_message': str(error)}]]}}
                finally:
                    running.discard(prompt_id)

            @fake_server.routes.post('/prompt')
            async def post_prompt(request):
                body = await request.json()
                if running:
                    return web.json_response({'error': 'A second render was queued before the first finished.'}, status=400)
                received.append(body['prompt']['1']['inputs'])
                running.add(body['prompt_id'])
                tasks.append(asyncio.create_task(render(body['prompt'], body['prompt_id'])))
                return web.json_response({'prompt_id': body['prompt_id'], 'number': len(received), 'node_errors': {}})

            @fake_server.routes.get('/history/{prompt_id}')
            async def get_history(request):
                value = request.match_info['prompt_id']
                return web.json_response({value: history[value]} if value in history else {})

            @fake_server.routes.get('/queue')
            async def get_queue(request):
                return web.json_response({'queue_running': [[0, value, {}, {}, []] for value in running], 'queue_pending': []})

            graph = {
                '1': {'class_type': 'AlphaSceneDirector', 'inputs': {'scene_plan': '', 'first_image': '', 'last_image': '', 'positive': '', 'negative': '', 'frames': 3, 'fps': 2.0, 'seed': 7, 'run_id': 'preview', 'clip_id': 'clip-001'}},
                '2': {'class_type': 'ControlledVideoModel', 'inputs': {'first': ['1', 0], 'last': ['1', 1], 'text': ['1', 2], 'frames': ['1', 5], 'seed': ['1', 4]}},
                '3': {'class_type': 'AlphaSceneCheckpoint', 'inputs': {'images': ['2', 0], 'run_id': ['1', 8], 'clip_id': ['1', 9]}},
                '4': {'class_type': 'SaveVideo', 'inputs': {'images': ['3', 0], 'fps': ['1', 6], 'filename_prefix': ['1', 7]}},
            }
            request_body = {'plan': {'version': 1, 'project': 'HTTP integration', 'defaults': {'first_image': 'first.png', 'last_image': 'last.png', 'frames': 3, 'fps': 2, 'seed': 7}, 'scenes': [{'id': 'opening', 'title': 'Opening', 'prompt': 'An image changes from red to blue.', 'clips': 2}]}, 'workflow': graph, 'director_id': '1', 'checkpoint_id': '3', 'video_output_id': '4'}
            app = web.Application()
            app.add_routes(fake_server.routes)
            async with TestServer(app) as server:
                async with aiohttp.ClientSession() as session:
                    async with session.post(server.make_url('/alpha_scene_director/validate'), json=request_body) as response:
                        payload = await response.json()
                        self.assertEqual(response.status, 200, payload)
                    async with session.post(server.make_url('/alpha_scene_director/jobs'), json=request_body) as response:
                        job = await response.json()
                        self.assertEqual(response.status, 200, job)
                # Browser/client session is now closed; server-side work continues.
                async def wait_for_completion():
                    while manager.get(job['job_id'])['status'] in ('running', 'pausing'):
                        await asyncio.sleep(0.05)
                await asyncio.wait_for(wait_for_completion(), timeout=15)
                result = manager.get(job['job_id'])
                self.assertEqual(result['status'], 'completed', result)
                self.assertEqual(result['completed'], 2)
                self.assertEqual(len(received), 2)
                self.assertEqual(received[0]['first_image'], 'first.png')
                self.assertEqual(received[1]['first_image'], result['clips'][0]['receipt']['last_frame'])
                self.assertTrue((output_root / 'alpha_scene_director' / job['job_id'] / 'job.json').is_file())
                self.assertEqual(len(list(output_root.rglob('*.mp4'))), 2)
                async with aiohttp.ClientSession() as session:
                    async with session.get(server.make_url('/alpha_scene_director/jobs')) as response:
                        saved = await response.json()
                        self.assertEqual(saved[0]['completed'], 2)
            await asyncio.gather(*tasks)


if __name__ == '__main__':
    unittest.main()
