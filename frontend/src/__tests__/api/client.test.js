import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { get, post, patch, del, ApiError } from '../../api/client';

// Mock global fetch
const mockFetch = vi.fn();
global.fetch = mockFetch;

function jsonResponse(data, status = 200) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(data),
  });
}

function noContentResponse() {
  return Promise.resolve({
    ok: true,
    status: 204,
    json: () => Promise.reject(new Error('No content')),
  });
}

function errorResponse(status, detail = null) {
  const data = detail ? { detail } : null;
  return Promise.resolve({
    ok: false,
    status,
    json: () => (data ? Promise.resolve(data) : Promise.reject(new Error('no body'))),
  });
}

beforeEach(() => {
  mockFetch.mockReset();
});


describe('get()', () => {
  it('calls fetch with correct URL', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }));
    const result = await get('/projects');
    expect(mockFetch).toHaveBeenCalledWith(
      'http://localhost:8000/api/projects',
      expect.objectContaining({ headers: { 'Content-Type': 'application/json' } })
    );
    expect(result).toEqual({ id: 1 });
  });

  it('appends query params', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await get('/tickets', { status: 'open', project_id: 1 });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('status=open');
    expect(url).toContain('project_id=1');
  });

  it('skips null/undefined params', async () => {
    mockFetch.mockReturnValue(jsonResponse([]));
    await get('/tickets', { status: null, type: undefined, real: 'yes' });
    const url = mockFetch.mock.calls[0][0];
    expect(url).toContain('real=yes');
    expect(url).not.toContain('status');
    expect(url).not.toContain('type');
  });
});


describe('post()', () => {
  it('sends POST with JSON body', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1 }, 201));
    const result = await post('/projects', { name: 'Test' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(config.method).toBe('POST');
    expect(JSON.parse(config.body)).toEqual({ name: 'Test' });
    expect(result).toEqual({ id: 1 });
  });
});


describe('patch()', () => {
  it('sends PATCH with JSON body', async () => {
    mockFetch.mockReturnValue(jsonResponse({ id: 1, name: 'Updated' }));
    await patch('/projects/1', { name: 'Updated' });
    const [url, config] = mockFetch.mock.calls[0];
    expect(config.method).toBe('PATCH');
    expect(url).toBe('http://localhost:8000/api/projects/1');
  });
});


describe('del()', () => {
  it('sends DELETE and returns null for 204', async () => {
    mockFetch.mockReturnValue(noContentResponse());
    const result = await del('/projects/1');
    expect(result).toBeNull();
    expect(mockFetch.mock.calls[0][1].method).toBe('DELETE');
  });
});


describe('Error handling', () => {
  it('throws ApiError on non-ok response with detail', async () => {
    mockFetch.mockReturnValue(errorResponse(404, 'Not found'));
    try {
      await get('/projects/999');
      expect.fail('Should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(404);
      expect(err.message).toBe('Not found');
      expect(err.data).toEqual({ detail: 'Not found' });
    }
  });

  it('throws ApiError with fallback message when no JSON body', async () => {
    mockFetch.mockReturnValue(errorResponse(500));
    try {
      await get('/status');
      expect.fail('Should have thrown');
    } catch (err) {
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(500);
      expect(err.message).toContain('500');
    }
  });
});
