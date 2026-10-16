import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({base:'/chat/',plugins:[react()],server:{proxy:{'/v1':{target:process.env.HARNESS_DEV_TARGET || 'http://127.0.0.1:8200',changeOrigin:true}}}});
