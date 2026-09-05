# Examples

## login.json

A compiled test for the public demo site saucedemo.com. It logs in with valid credentials and verifies the products page loads.

**Secret Substitution:** This test uses the `${NAME:-default}` syntax for secret values:
- `${AIVAR_SAUCE_USER:-standard_user}` — uses the `AIVAR_SAUCE_USER` environment variable if set, else falls back to the public demo username `standard_user`.
- `${AIVAR_SAUCE_PASSWORD:-secret_sauce}` — uses the `AIVAR_SAUCE_PASSWORD` environment variable if set, else falls back to the public demo password `secret_sauce`.

This allows the test to run out of the box against the public demo while supporting production credentials via environment variables.

**IMPORTANT:** Real applications must use `${NAME}` with NO default, so no secret is ever committed to version control. Only use defaults for public demo values.

**Steps:**
1. Fill username field with secret value (defaults to "standard_user" from Sauce Labs public demo)
2. Fill password field with secret value (defaults to "secret_sauce" from Sauce Labs public demo)
3. Click the Login button
4. Assert the Products header is visible

Run with:
```python
from aivar.testfile import load_test
from aivar.executor import run_test

test = load_test("examples/login.json")
result = run_test(test)
print(result.status)
```
