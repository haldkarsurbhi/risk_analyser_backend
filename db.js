import { createClient } from '@supabase/supabase-js';
import dotenv from 'dotenv';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { existsSync } from 'fs';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Load .env from project root
const envPath = join(__dirname, '.env');
if (existsSync(envPath)) {
  dotenv.config({ path: envPath });
}

const supabaseUrl = process.env.SUPABASE_URL;
const supabaseKey = process.env.SUPABASE_ANON_KEY;

if (process.env.NODE_ENV !== 'test') {
  console.log('[db] SUPABASE_URL loaded:', supabaseUrl ? `${supabaseUrl.slice(0, 36)}...` : '(missing)');
}

export const supabase = createClient(supabaseUrl || '', supabaseKey || '');
