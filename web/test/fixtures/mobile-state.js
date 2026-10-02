export const now = Date.now()/1000;
export const names = ['stoat','numbat-claude-opus-karansmbp','hoopoe-codex-gpt5-karanslinux','ferret','hedgehog','smew','tapir','jerboa'];
export const image = 'b'.repeat(64)+'.png';
export const file = 'a'.repeat(64)+'.file.mobile-layout-review-with-a-long-filename.txt';
export function fixture() { return {
 now, recipients: names.map((user_id,i)=>({user_id, node:i%2?'karans-mbp':'karans-linux', flavor:i%2?'claude':'codex', model:i%2?'claude-opus-5-5':'gpt-6.1-sol', pane_alive:true, tmux_pane:`%${100+i}`, pane_label:'agent-swarm:0.'+i, registered_at:now-1000, team_id:i<3?1:null, activity:{status:['working','needs_attention','idle','unknown'][i%4]}, summaries:[{text:'Reviewing mobile dashboard navigation',ts:now,source:'agent'},{text:'Earlier: checking task controls',ts:now-50,source:'agent'}]})).concat([{user_id:'stopped-agent',node:'karans-mbp',flavor:'codex',pane_alive:false,registered_at:now-1000,summaries:[]}]),
 nodes:[{name:'karans-linux',connected:true,local:true,harnesses:['codex','claude']},{name:'karans-mbp',connected:true,harnesses:['codex','claude']}],
 teams:[{id:1,name:'agent-swarm',queen:'stoat',members:names.slice(0,3)}],
 tasks:[{id:73,title:'Make the dashboard mobile friendly',description:'Review phone and tablet layouts, task assignment, and attachments.',assignee:'stoat',status:'picked_up',created_at:now-1000,updated_at:now,depends_on:[],attachments:[file,image],worktree:'/Users/karan/agent-swarm-task-73'}, {id:74,title:'Long path regression',description:'/Users/karan/'+('very-long-path-component-'.repeat(8)),status:'open',created_at:now,updated_at:now,depends_on:[73],attachments:[]}, {id:72,title:'Preserve working halos',status:'done',assignee:names[2],created_at:now-2000,updated_at:now-500,note:'Verify green halos in both hive and roster.',depends_on:[],attachments:[]}],
 messages:[{id:1,sender:'owner',recipient:'stoat',content:'Please review mobile layouts.\n\n```\n'+('long_terminal_line_'.repeat(20))+'\n```',ts:now,status:'delivered',attachments:[file,image]},{id:2,sender:'stoat',recipient:'owner',content:'Testing phone and tablet navigation.',ts:now,status:'delivered',attachments:[]}]
}; }
export async function mock(page,state=fixture()) {
 await page.route('**/api/state',r=>r.fulfill({json:state}));
 await page.route('**/api/peek/**',r=>r.fulfill({json:{pane_label:'agent-swarm:0.1',text:'Reviewing mobile layouts\n'+('long_output_'.repeat(45))}}));
 await page.route('**/attachments/**',r => r.request().url().endsWith('.png')
   ? r.fulfill({body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#f2a93b"/></svg>',contentType:'image/svg+xml'})
   : r.fulfill({body:'mobile QA attachment',contentType:'text/plain'}));
 return state;
}
