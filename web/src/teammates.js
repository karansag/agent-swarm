// No imports, so `node --test web/test` can exercise it without a browser.

// The agent's team and its members to switch between: live members plus the
// agent itself, queen first, then by name, so the order never shifts with
// activity and Alt+[ / Alt+] always step the same way. Null without a team.
export function teammates(recipients, teams, user) {
  const me = recipients.find(r => r.user_id === user);
  const team = me && (teams || []).find(t => t.id === me.team_id);
  if (!team) return null;
  const members = recipients
    .filter(r => r.team_id === team.id && (r.pane_alive || r.user_id === user))
    .sort((a, b) => (b.user_id === team.queen) - (a.user_id === team.queen) || a.user_id.localeCompare(b.user_id));
  return { team, members };
}

// The member `by` steps from `user`, wrapping around; null with no one else.
export function stepTeammate(members, user, by) {
  const ids = members.map(m => m.user_id);
  if (ids.length < 2) return null;
  const i = Math.max(0, ids.indexOf(user));
  return ids[(i + by + ids.length) % ids.length];
}
