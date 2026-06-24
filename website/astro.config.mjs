// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

// https://astro.build/config
export default defineConfig({
	site: 'https://hermes-router.vercel.app',
	integrations: [
		starlight({
			title: 'hermes-router',
			description: 'Keep your AI app online for free — a self-hosted load balancer across free AI providers (OpenAI & Anthropic compatible).',
			logo: { src: './src/assets/logo.png', alt: 'hermes-router' },
			favicon: '/favicon.png',
			customCss: ['./src/styles/custom.css'],
			social: [
				{ icon: 'github', label: 'GitHub', href: 'https://github.com/Shaf2665/Hermes-router' },
			],
			sidebar: [
				{
					label: 'Start Here',
					items: [
						{ label: 'Introduction', slug: 'index' },
						{ label: 'Getting Started', slug: 'getting-started' },
						{ label: 'Core Concepts', slug: 'concepts' },
					],
				},
				{
					label: 'Set It Up',
					items: [
						{ label: 'Deployment', slug: 'deployment' },
						{ label: 'Providers', slug: 'providers' },
						{ label: 'Configuration', slug: 'configuration' },
					],
				},
				{
					label: 'Build With It',
					items: [
						{ label: 'Usage', slug: 'usage' },
						{ label: 'Build an Agent', slug: 'build-an-agent' },
					],
				},
				{
					label: 'Operate',
					items: [
						{ label: 'Monitoring', slug: 'monitoring' },
					],
				},
				{
					label: 'Under the Hood',
					items: [
						{ label: 'How it works', slug: 'architecture' },
					],
				},
				{
					label: 'Tools',
					items: [
						{ label: 'VS Code Extension', slug: 'vscode-extension' },
					],
				},
			],
		}),
	],
});
