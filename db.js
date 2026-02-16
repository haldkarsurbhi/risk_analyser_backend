import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load backend/.env explicitly (fallback to backend/backend/.env when present)
const envPath = join(__dirname, '.env');
const envPathNested = join(__dirname, 'backend', '.env');
if (existsSync(envPath)) {
  dotenv.config({ path: envPath });
} else if (existsSync(envPathNested)) {
  dotenv.config({ path: envPathNested });
}

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_ANON_KEY;

if (process.env.NODE_ENV !== 'test') {
  console.log('[db] SUPABASE_URL loaded:', supabaseUrl ? `${supabaseUrl.slice(0, 36)}...` : '(missing)');
}

export const supabase = createClient(supabaseUrl || '', supabaseKey || '');
