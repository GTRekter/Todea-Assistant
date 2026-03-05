const express = require('express');
const http = require('http');
const https = require('https');
const path = require('path');
const { URL } = require('url');

const app = express();
const PORT = process.env.PORT || 80;
const staticDir = path.resolve(__dirname, '../build');
const TRAINING_HUB_TARGET = process.env.TRAINING_HUB_PROXY_TARGET || 'http://todea-training-hub:3500';
const HUB_TARGET = process.env.HUB_PROXY_TARGET || 'http://todea-agent-hub:3100';

// Route hub API paths to the hub service — mirrors what the ingress does in-cluster.
for (const hubPath of ['/chat', '/models', '/conversations', '/settings']) {
  app.use(hubPath, (req, res) => {
    const base = new URL(`${HUB_TARGET}/`);
    const upstreamUrl = new URL((hubPath + req.url).replace(/^\/+/, ''), base);
    const client = upstreamUrl.protocol === 'https:' ? https : http;
    req.setTimeout(0);
    const headers = { ...req.headers, host: upstreamUrl.host };
    delete headers.origin;
    delete headers.referer;
    const proxyReq = client.request(upstreamUrl, { method: req.method, headers }, (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 500, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    });
    proxyReq.on('error', (err) => {
      console.error('Hub proxy error:', err.message);
      if (!res.headersSent) res.status(502).json({ detail: 'Hub unreachable' });
      else res.end();
    });
    if (req.method === 'GET' || req.method === 'HEAD') proxyReq.end();
    else req.pipe(proxyReq, { end: true });
  });
}

// Simple streaming-friendly proxy so the browser can hit the in-cluster
// training hub via the same origin. Avoids exposing the hub through ingress.
app.use('/training-hub', (req, res) => {
  const targetBase = new URL(TRAINING_HUB_TARGET.endsWith('/') ? TRAINING_HUB_TARGET : `${TRAINING_HUB_TARGET}/`);
  const upstreamUrl = new URL(req.url.startsWith('/') ? req.url.slice(1) : req.url, targetBase);
  const client = upstreamUrl.protocol === 'https:' ? https : http;

  req.setTimeout(0); // keep long-running log streams alive

  const headers = { ...req.headers, host: upstreamUrl.host };
  delete headers.origin;
  delete headers.referer;

  const proxyReq = client.request(
    upstreamUrl,
    {
      method: req.method,
      headers,
    },
    (proxyRes) => {
      res.writeHead(proxyRes.statusCode || 500, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    },
  );

  proxyReq.on('error', (err) => {
    console.error('Training hub proxy error:', err.message);
    if (!res.headersSent) res.status(502).json({ detail: 'Training hub unreachable' });
    else res.end();
  });

  if (req.method === 'GET' || req.method === 'HEAD') {
    proxyReq.end();
  } else {
    req.pipe(proxyReq, { end: true });
  }
});

app.use(express.static(staticDir));
app.get('/healthz', (_req, res) => {
  res.status(200).json({ status: 'ok' });
});

app.get('*', (_req, res) => {
  res.sendFile(path.join(staticDir, 'index.html'));
});

app.listen(PORT, () => {
  console.log(`Frontend server listening on port ${PORT}`);
});
