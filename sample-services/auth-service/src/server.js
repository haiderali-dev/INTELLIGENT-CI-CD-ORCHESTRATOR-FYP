/** auth-service entry point. */
import { createServer } from 'node:http';
import { handle, SERVICE_NAME } from './app.js';

const port = Number(process.env.PORT ?? 8080);

createServer(handle).listen(port, '0.0.0.0', () => {
  console.log(`${SERVICE_NAME} listening on ${port}`);
});
