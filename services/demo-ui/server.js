import express from 'express';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const app = express();
const port = Number(process.env.PORT || 8501);

const services = {
  patient: process.env.PATIENT_SERVICE_URL || 'http://localhost:5001',
  doctor: process.env.DOCTOR_SCHEDULE_SERVICE_URL || 'http://localhost:5002',
  appointment: process.env.APPOINTMENT_SERVICE_URL || 'http://localhost:5003',
  prescription: process.env.PRESCRIPTION_SERVICE_URL || 'http://localhost:5004',
  billing: process.env.BILLING_SERVICE_URL || 'http://localhost:5005'
};

app.use(express.json({ limit: '1mb' }));

function correlationId() {
  return `corr-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function normalizeError(service, status, body, fallback) {
  return {
    code: `${service.toUpperCase()}_${status}`,
    message: body?.message || body?.error || fallback || 'Request failed',
    correlationId: correlationId(),
    details: body || null
  };
}

function paginate(items, query) {
  const page = Math.max(Number(query.page || 1), 1);
  const pageSize = Math.min(Math.max(Number(query.pageSize || 10), 1), 50);
  const start = (page - 1) * pageSize;
  return {
    items: items.slice(start, start + pageSize),
    page,
    pageSize,
    total: items.length
  };
}

function applyReadModelFilters(service, items, query) {
  if (!Array.isArray(items)) {
    return items;
  }

  let filtered = [...items];
  if (service === 'patient') {
    const name = String(query.name || '').trim().toLowerCase();
    const phone = String(query.phone || '').trim().toLowerCase();
    if (name) {
      filtered = filtered.filter((item) => String(item.name || '').toLowerCase().includes(name));
    }
    if (phone) {
      filtered = filtered.filter((item) => String(item.phone || '').toLowerCase().includes(phone));
    }
  }

  if (service === 'doctor' && query.department) {
    const department = String(query.department).toLowerCase();
    filtered = filtered.filter((item) => String(item.department || '').toLowerCase() === department);
  }

  return paginate(filtered, query);
}

function targetPathFrom(versionedPath) {
  if (versionedPath === 'v1') {
    return '/';
  }
  if (versionedPath.startsWith('v1/')) {
    return `/${versionedPath.slice(3)}`;
  }
  return `/${versionedPath}`;
}

app.all(/^\/api\/([^/]+)\/(.+)$/, async (req, res) => {
  const service = req.params[0];
  const pathPart = req.params[1];
  const baseUrl = services[service];

  if (!baseUrl) {
    return res.status(404).json(normalizeError(service, 404, null, 'Unknown service'));
  }

  const targetPath = targetPathFrom(pathPart);
  const upstreamUrl = new URL(targetPath, baseUrl);
  for (const [key, value] of Object.entries(req.query)) {
    upstreamUrl.searchParams.set(key, value);
  }

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (req.headers['idempotency-key']) {
      headers['Idempotency-Key'] = req.headers['idempotency-key'];
    }

    const upstream = await fetch(upstreamUrl, {
      method: req.method,
      headers,
      body: ['GET', 'HEAD'].includes(req.method) ? undefined : JSON.stringify(req.body || {})
    });

    const text = await upstream.text();
    let body = null;
    try {
      body = text ? JSON.parse(text) : null;
    } catch {
      body = text ? { raw: text } : null;
    }

    if (!upstream.ok) {
      return res.status(upstream.status).json(normalizeError(service, upstream.status, body));
    }

    const shaped = req.method === 'GET'
      ? applyReadModelFilters(service, body, req.query)
      : body;
    return res.status(upstream.status).json(shaped);
  } catch (error) {
    return res.status(503).json(normalizeError(service, 503, null, error.message));
  }
});

app.get('/api/service-map', (_req, res) => {
  res.json(Object.fromEntries(Object.entries(services).map(([key, value]) => [key, value])));
});

app.use(express.static(path.join(__dirname, 'dist')));

app.get('*', (_req, res) => {
  res.sendFile(path.join(__dirname, 'dist', 'index.html'));
});

app.listen(port, '0.0.0.0', () => {
  console.log(`HMS demo UI listening on port ${port}`);
});
