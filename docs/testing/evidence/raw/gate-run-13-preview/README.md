# Pipeline preview failure, gate run 13

The browser received HTTP 201 with a validated Pipeline, immediately fetched the conversation,
and received only its original intent messages. No pipeline message was visible, so the preview
stayed empty and the Jenkinsfile tab never appeared. The browser timed out after eight minutes.
D-083 records the cause and fix: request transactions now commit before response bytes are sent.

- `trace.zip`: the original browser trace with seven temporary authentication values redacted
  from its resources, headers and form input records before archiving. Resource names and trace
  references are retained so the trace can be viewed normally.
- `test-failed-1.png`: the original failed-page screenshot.
- `error-context.md`: Playwright's original failure description and page snapshot.

The temporary test account was deactivated by the test runner. This is diagnostic evidence,
not a login fixture. The exact browser flow passed in 17.4 seconds after the backend fix.
