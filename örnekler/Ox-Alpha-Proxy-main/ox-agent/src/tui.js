import readline from 'readline';
import chalk from 'chalk';
import ora from 'ora';
import { runAgentLoop } from './agent.js';
import { getAllTools, getToolsets } from './tools.js';
import { createSession, listSessions } from './session.js';

const BANNER = `
${chalk.yellow.bold('  ██████╗ ██╗  ██╗')}${chalk.dim('      OX-AGENT v1.0.0 (stealth)')}
${chalk.yellow.bold(' ██╔═══██╗╚██╗██╔╝')}  ${chalk.dim('1M context • toolsets • workspaces • memory')}
${chalk.yellow.bold(' ██║   ██║ ╚███╔╝ ')}  ${chalk.cyan('Available Tools:')} ${chalk.dim('bash, read, write, edit, glob, grep, webfetch, browser, vision, todo, delegate')}
${chalk.yellow.bold(' ██║   ██║ ██╔██╗ ')}  ${chalk.cyan('Available Skills:')} ${chalk.dim('ox-code, ox-research, ox-browser, horizone-code, plan-master')}
${chalk.yellow.bold(' ╚██████╔╝██╔╝ ██╗')}  ${chalk.cyan('Profiles:')} ${chalk.dim('custom, code-review, plan, fast, thinking')}
${chalk.yellow.bold('  ╚═════╝ ╚═╝  ╚═╝')}
`;

export async function startInteractive(opts) {
  console.clear();
  console.log(BANNER);
  console.log(chalk.dim(`  Session: ${createSession().id}  •  Model: ${opts.model}  •  Toolsets: ${opts.toolsets}  •  Base: ${opts.baseUrl}`));
  console.log(chalk.dim('  Type /help for commands, /model to switch, /tools to configure, Ctrl+C to exit\n'));

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout, prompt: chalk.yellow('ox-agent› ') });
  let history = [];

  rl.prompt();
  rl.on('line', async (line) => {
    const input = line.trim();
    if (!input) { rl.prompt(); return; }

    // slash commands like Hermes
    if (input.startsWith('/')) {
      const [cmd, ...args] = input.slice(1).split(' ');
      switch (cmd) {
        case 'help': console.log(chalk.dim('/new /model /tools /skills /compress /usage /session /workspace /clear /exit')); break;
        case 'new': case 'reset': history = []; console.log(chalk.green('New session started')); break;
        case 'model': console.log(chalk.dim('Use: ox-agent model')); break;
        case 'tools': console.log(chalk.dim('Available toolsets:'), getToolsets().join(', ')); break;
        case 'skills': console.log(chalk.dim('Skills: ox-code, ox-research, ox-browser, horizone-code')); break;
        case 'usage': console.log(chalk.dim(`History: ${history.length} turns`)); break;
        case 'clear': console.clear(); console.log(BANNER); break;
        case 'exit': case 'quit': rl.close(); return;
        default: console.log(chalk.red(`Unknown /${cmd}`));
      }
      rl.prompt();
      return;
    }

    const spinner = ora({ text: chalk.dim('Ox Alpha thinking…'), spinner: 'dots' }).start();
    try {
      const { text, toolCalls } = await runAgentLoop(input, history, opts);
      spinner.stop();
      // Render markdown-ish
      console.log(chalk.white(text));
      if (toolCalls && toolCalls.length) {
        console.log(chalk.dim(`  ↳ tools: ${toolCalls.map(t=>t.function.name).join(', ')}`));
      }
      history.push({ role: 'user', content: input }, { role: 'assistant', content: text });
      if (history.length > 40) history = history.slice(-30); // auto-compress
    } catch (e) {
      spinner.fail(chalk.red(e.message));
    }
    rl.prompt();
  });

  rl.on('close', () => {
    console.log(chalk.dim('\nBye — session saved.'));
    process.exit(0);
  });
}
