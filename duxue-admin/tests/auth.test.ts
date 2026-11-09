import test from 'node:test';
import assert from 'node:assert/strict';
import {
  passwordHash,
  checkPassword,
  checkOrigin,
  ApiError,
} from '../src/lib/auth';
test('password hashes are salted and checked without storing plaintext', () => {
  const a = passwordHash('test-password-long-enough'),
    b = passwordHash('test-password-long-enough');
  assert.notEqual(a, b);
  assert(checkPassword('test-password-long-enough', a));
  assert(!checkPassword('wrong', a));
  assert.throws(() => passwordHash('short'));
});
test('mutation rejects cross-site origins and handles Next internal URL normalization', () => {
  checkOrigin(
    new Request('http://localhost:3021/api/drafts', {
      headers: { host: '127.0.0.1:3021', origin: 'http://127.0.0.1:3021' },
    }),
  );
  assert.throws(
    () =>
      checkOrigin(
        new Request('http://localhost:3021/api/drafts', {
          headers: { host: '127.0.0.1:3021', origin: 'https://other.test' },
        }),
      ),
    ApiError,
  );
  assert.throws(
    () => checkOrigin(new Request('http://localhost:3021/api/drafts')),
    ApiError,
  );
});
