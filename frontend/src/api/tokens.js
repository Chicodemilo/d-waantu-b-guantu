import { get } from './client';

export function getTokenAudit() {
  return get('/tokens/audit');
}
