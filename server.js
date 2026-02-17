/**
 * Risk Analysis Tech Pack - Backend
 * Main server entry point.
 */
import express from 'express';
import cors from 'cors';
import path from 'path';
import fs from 'fs';
import { fileURLToPath } from 'url';

import uploadRoutes from "./routes/uploadRoutes.js";
import analysisRoutes from './routes/analysisRoutes.js';
import techpackRoutes from './routes/techpack.js';
import { supabase } from './db.js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;

app.use(cors());
app.use(express.json());

const uploadsDir = path.join(__dirname, 'uploads');
if (!fs.existsSync(uploadsDir)) {
  fs.mkdirSync(uploadsDir, { recursive: true });
}

app.get('/', (req, res) => {
  res.send('Backend is running!');
});
app.get('/health', (req, res) => {
  res.json({ status: 'OK', service: 'Risk Analysis API', version: '1.0.0' });
});

app.get('/test-db', async (req, res) => {
  const { data, error } = await supabase
    .from('styles')
    .select('*')
    .limit(1);
  if (error) return res.json({ error });
  res.json({ success: true, data });
});

app.get('/insert-test-style', async (req, res) => {
  const { data, error } = await supabase
    .from('styles')
    .insert([
      {
        style_ref: 'TEST-001',
        buyer: 'TEST BUYER',
        garment_type: 'Shirt',
        fabric_type: 'Woven',
        wash_type: 'None',
        complexity: 5.5
      }
    ])
    .select();
  if (error) return res.json({ error });
  res.json({ inserted: data });
});

app.use('/', analysisRoutes);
app.use('/upload', uploadRoutes);
app.use('/api/techpack', techpackRoutes);

app.use((err, req, res, next) => {
  console.error('[ERROR]', err.stack);
  res.status(500).json({
    error: 'Internal server error',
    message: err.message,
  });
});

app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});

export default app;
