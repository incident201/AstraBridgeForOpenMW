import {defineConfig} from 'vite';
import {svelte} from '@sveltejs/vite-plugin-svelte';
import {resolve} from 'node:path';
export default defineConfig({root:'frontend',base:'./',plugins:[svelte({configFile:resolve('svelte.config.js')})],build:{outDir:'../out/frontend',emptyOutDir:true}});
