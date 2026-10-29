import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
// The backend only accepts writes from its own origin; the dev proxy presents requests as same-origin.
const backend='http://127.0.0.1:8877';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':{target:backend,changeOrigin:true,headers:{origin:backend}}}},build:{chunkSizeWarningLimit:1600}});
