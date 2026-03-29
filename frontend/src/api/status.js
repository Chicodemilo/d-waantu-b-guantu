import { get } from './client';

export function getStatus() {
  return get('/status');
}

export function getTestCoverage() {
  return get('/status/test-coverage');
}

export function getCodeStandards() {
  return get('/status/code-standards');
}
