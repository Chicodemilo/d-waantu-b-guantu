// Path: src/api/tlChannel.js
// File: tlChannel.js
// Created: 2026-06-23
// Purpose: API wrapper for the cross-project team-lead (Archie) messaging channel (DWB-440 read view; backend DWB-436/437/438). getTLChannel returns the full channel message list (direct + broadcast) across all projects, newest first.
// Caller: pages/ArchieChannelPage.jsx
// Callees: ./client (get)
// Data In: optional { limit } query params
// Data Out: Array of channel message rows (see ArchieChannelPage.normalizeMessage for the bound shape)
// Last Modified: 2026-06-23

import { get } from './client';

// GET list endpoint for the TL channel. Path confirmed against Barry's
// DWB-436/437/438 contract; rebind here if the final route differs.
export function getTLChannel(params = {}) {
  return get('/tl-channel', params);
}
