// Node 18 lacks the browser File global used by upload-contract tests.
// Browsers and newer Node releases already provide it.
globalThis.File = require("buffer").File;
globalThis.crypto = require("crypto").webcrypto;
