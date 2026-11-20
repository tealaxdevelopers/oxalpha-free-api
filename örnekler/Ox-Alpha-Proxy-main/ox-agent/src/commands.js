import inquirer from 'inquirer';
import chalk from 'chalk';
import Conf from 'conf';
const conf = new Conf({ projectName: 'ox-agent' });

export async function handleModel(){
  const { provider } = await inquirer.prompt([{ type:'list', name:'provider', message:'Provider', choices:['ox-alpha (local proxy)','openai','anthropic','custom'] }]);
  const { model } = await inquirer.prompt([{ type:'input', name:'model', message:'Model id', default:'ox-alpha' }]);
  const { baseUrl } = await inquirer.prompt([{ type:'input', name:'baseUrl', message:'Base URL', default:'http://localhost:3000/v1' }]);
  conf.set('model', { provider, model, baseUrl });
  console.log(chalk.green(`Saved model ${provider}/${model} @ ${baseUrl}`));
}
export async function handleTools(){
  const choices = ['web','terminal','file','browser','vision','code','todo','memory','all'];
  const { toolsets } = await inquirer.prompt([{ type:'checkbox', name:'toolsets', message:'Enable toolsets', choices, default:['all'] }]);
  conf.set('toolsets', toolsets.join(','));
  console.log(chalk.green('Toolsets:'), toolsets.join(', '));
}
export async function handleConfig(action, key, value){
  if(action==='get'){
    if(key) console.log(`${key}=${conf.get(key)}`);
    else console.log(conf.store);
  } else if(action==='set' && key){
    conf.set(key, value);
    console.log(chalk.green(`Set ${key}=${value}`));
  } else {
    console.log('Usage: ox-agent config get|set <key> [value]');
  }
}
export async function handleSession(action){
  const { listSessions, pruneSessions } = await import('./session.js');
  if(action==='prune') pruneSessions();
  else console.log(listSessions());
}
