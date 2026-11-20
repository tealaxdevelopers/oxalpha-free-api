#!/usr/bin/env node
import { Command } from 'commander';
import chalk from 'chalk';
import boxen from 'boxen';
import { startInteractive } from '../src/tui.js';
import { handleModel, handleTools, handleConfig, handleSession } from '../src/commands.js';

const program = new Command();

program
  .name('ox-agent')
  .description('OX-AGENT — stealth reasoning CLI for Ox Alpha (better than Hermes)')
  .version('1.0.0');

program
  .command('chat', { isDefault: true })
  .description('Start interactive TUI (default)')
  .option('--toolsets <list>', 'toolsets: web,terminal,browser,file,vision,code,all', 'all')
  .option('--model <model>', 'model id', 'ox-alpha')
  .option('--workspace <dir>', 'isolated workspace dir')
  .option('--base-url <url>', 'Ox Alpha Proxy base URL', 'http://localhost:3000/v1')
  .action(async (opts) => {
    await startInteractive(opts);
  });

program
  .command('model')
  .description('Choose LLM provider/model')
  .action(async () => { await handleModel(); });

program
  .command('tools')
  .description('Configure toolsets')
  .action(async () => { await handleTools(); });

program
  .command('config')
  .description('config get/set')
  .argument('<action>', 'get|set')
  .argument('[key]', 'key')
  .argument('[value]', 'value')
  .action(async (action, key, value) => { await handleConfig(action, key, value); });

program
  .command('session')
  .description('session list/prune')
  .argument('[action]', 'list|prune', 'list')
  .action(async (action) => { await handleSession(action); });

program
  .command('run')
  .description('Run single prompt non-interactive')
  .argument('<prompt>', 'prompt')
  .option('--model <model>', 'model', 'ox-alpha')
  .action(async (prompt, opts) => {
    const { runOnce } = await import('../src/agent.js');
    const out = await runOnce(prompt, opts);
    console.log(out);
  });

program.parse();

// Hermes-like banner on --help
if (process.argv.length === 2) {
  console.log(boxen(chalk.bold.yellow(' OX-AGENT ') + chalk.dim('v1.0.0 — stealth reasoning, 1M context'), { padding: 1, borderColor: 'yellow' }));
}
