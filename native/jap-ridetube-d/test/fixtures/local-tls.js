'use strict';
// Test processes only: the local TLS origin uses the adjacent self-signed certificate.
// The daemon deliberately clears its child's environment, so preload this fixture explicitly.
process.env.NODE_TLS_REJECT_UNAUTHORIZED = '0';
