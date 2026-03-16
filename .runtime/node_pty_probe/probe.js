const pty = require('node-pty');
const shell = process.env.COMSPEC || 'cmd.exe';
const term = pty.spawn(shell, [], {name:'xterm-color', cols:120, rows:30, cwd: process.cwd(), env: process.env});
let buf = '';
let done = false;
const timer = setTimeout(() => {
  if (!done) {
    console.log('FOUND=false');
    console.log(buf.slice(-500));
    term.kill();
    process.exit(1);
  }
}, 4000);
term.onData((d) => {
  buf += d;
  if (!done && buf.includes('NODE_PTY_OK')) {
    done = true;
    clearTimeout(timer);
    console.log('FOUND=true');
    console.log(buf.slice(-500));
    term.kill();
    process.exit(0);
  }
});
term.write('echo NODE_PTY_OK\r');
