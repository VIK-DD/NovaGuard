// pm2 process definition for the NovaGuard bot.
//
// SETUP.md has always told operators to run this under pm2, but the settings
// that keep pm2 from making a bad day worse lived only in whatever `pm2 start`
// flags happened to be typed on the host - and therefore nowhere reviewable,
// nowhere in version control, and gone the moment the host is rebuilt.
//
// Start with:   pm2 start ecosystem.config.js && pm2 save
// Restart with: pm2 restart NovaGuard --update-env
//
// `--update-env` matters. pm2 captures the environment at `pm2 start` and
// re-injects that same copy on every plain restart, so a secret rotated in
// .env would not reach the process. core/config.py now treats .env as
// authoritative, which closes that hole from the other side, but the flag is
// still the honest way to restart after an environment change.

module.exports = {
  apps: [
    {
      name: "NovaGuard",
      script: "bot.py",
      interpreter: "venv/bin/python",
      cwd: __dirname,

      // One process. The bot holds a single Discord gateway session and a
      // single SQLite writer; a second instance would fight both.
      instances: 1,
      exec_mode: "fork",

      // A gateway client is long-lived by design. Restarting it because a file
      // changed is only ever a foot-gun in production.
      watch: false,
      autorestart: true,

      // The crash-loop guard. Without a minimum uptime pm2 counts a process
      // that dies during import as a successful start, so a bad deploy
      // restarts forever at full speed - hammering Discord's login endpoint,
      // which is how an IP earns a rate limit that outlasts the fix.
      min_uptime: "60s",
      max_restarts: 10,
      restart_delay: 5000,
      exp_backoff_restart_delay: 200,

      // The bot idles well under this; passing it means a leak, and a leak on
      // a small host ends with the OOM killer choosing what dies. Better that
      // pm2 chooses, and restarts cleanly.
      max_memory_restart: "500M",

      // Unbuffered, so a crash's last words actually reach the log instead of
      // sitting in a buffer that dies with the process.
      env: {
        PYTHONUNBUFFERED: "1",
      },

      // Timestamped, merged, and rotated by pm2-logrotate rather than growing
      // until the disk is full:
      //   pm2 install pm2-logrotate
      //   pm2 set pm2-logrotate:max_size 20M
      //   pm2 set pm2-logrotate:retain 14
      //   pm2 set pm2-logrotate:compress true
      time: true,
      merge_logs: true,
      out_file: "logs/novaguard-out.log",
      error_file: "logs/novaguard-error.log",

      // Give the bot time to close the gateway session and flush SQLite before
      // SIGKILL. discord.py's close() is not instant and a half-closed session
      // means Discord holds the old one open for a while.
      kill_timeout: 15000,
      listen_timeout: 10000,
    },
  ],
};
