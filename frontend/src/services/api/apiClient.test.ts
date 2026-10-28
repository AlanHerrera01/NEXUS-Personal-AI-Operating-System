import { afterEach, describe, expect, it, vi } from 'vitest';
import { API_BASE_URL, apiClient, setAccessToken } from './apiClient';
import { mcpApi } from './mcpApi';

afterEach(() => { setAccessToken(''); vi.unstubAllGlobals(); });

describe('authenticated same-origin API', () => {
  it('uses the current origin and sends the key only in the authorization header', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{"user_id":"owner"}'));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('private-key');
    await apiClient.get('/api/v1/auth/me');
    expect(API_BASE_URL).toBe('');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/auth/me', expect.objectContaining({ headers: expect.objectContaining({ Authorization: 'Bearer private-key' }) }));
  });

  it('allows bodyless MCP connection tests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    await mcpApi.test('server-id');
    expect(fetchMock).toHaveBeenCalledWith('/api/v1/mcp-servers/server-id/test', expect.objectContaining({ method: 'POST', body: undefined }));
  });

  it('clears rejected credentials and signals the login gate', async () => {
    const dispatchEvent = vi.fn();
    vi.stubGlobal('window', { dispatchEvent });
    const fetchMock = vi.fn().mockResolvedValueOnce(new Response('{"detail":"Invalid key"}', { status: 401 })).mockResolvedValueOnce(new Response('{}'));
    vi.stubGlobal('fetch', fetchMock);
    setAccessToken('expired-key');
    await expect(apiClient.get('/api/v1/auth/me')).rejects.toThrow('Invalid key');
    expect(dispatchEvent).toHaveBeenCalledOnce();
    await apiClient.get('/api/v1/auth/me');
    expect(fetchMock.mock.calls[1][1].headers).not.toHaveProperty('Authorization');
  });
});
