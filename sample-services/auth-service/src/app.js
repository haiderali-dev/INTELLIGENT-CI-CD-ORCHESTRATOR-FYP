/**
 * auth-service request handling.
 *
 * Kept in a separate module from the server so the tests can exercise the routing without binding
 * a port, which would make a test run flaky whenever 9002 happens to be busy.
 *
 * Node's standard library only: no dependencies. The agent runs `npm ci` for services that need
 * it, and a sample service with a lockfile to maintain adds nothing the experiment measures.
 */

const SERVICE_NAME = 'auth-service';
const VERSION = '1.0.0';

/** In-memory token store. Sample data; nothing here is a real credential. */
const sessions = new Map();

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Content-Length': Buffer.byteLength(payload),
  });
  res.end(payload);
}

/** Deterministic, non-cryptographic token. Sufficient for a sample service. */
function issueToken(username) {
  const token = `tok_${Buffer.from(username).toString('hex')}_${sessions.size + 1}`;
  sessions.set(token, { username, issuedAt: new Date().toISOString() });
  return token;
}

export function handle(req, res) {
  const url = new URL(req.url, `http://${req.headers.host ?? 'localhost'}`);

  // Liveness. deploy.sh polls this before declaring a deploy successful.
  if (url.pathname === '/health' && req.method === 'GET') {
    return json(res, 200, { status: 'ok', service: SERVICE_NAME });
  }

  // Which build is running. The commit is baked in at image build time; without it a deploy
  // cannot be distinguished from the one before it.
  if (url.pathname === '/version' && req.method === 'GET') {
    return json(res, 200, {
      service: SERVICE_NAME,
      version: VERSION,
      commit: process.env.GIT_COMMIT ?? 'unknown',
      environment: process.env.DEPLOY_ENV ?? 'local',
    });
  }

  if (url.pathname === '/login' && req.method === 'POST') {
    const username = url.searchParams.get('username');
    if (!username) {
      return json(res, 400, { error: 'username is required' });
    }
    return json(res, 201, { token: issueToken(username), username });
  }

  if (url.pathname === '/verify' && req.method === 'GET') {
    const token = url.searchParams.get('token') ?? '';
    const session = sessions.get(token);
    return session
      ? json(res, 200, { valid: true, ...session })
      : json(res, 401, { valid: false });
  }

  if (url.pathname === '/') {
    return json(res, 200, {
      service: SERVICE_NAME,
      endpoints: ['/health', '/version', '/login', '/verify'],
    });
  }

  return json(res, 404, { error: 'not found', path: url.pathname });
}

export function reset() {
  sessions.clear();
}

export { SERVICE_NAME, VERSION };
