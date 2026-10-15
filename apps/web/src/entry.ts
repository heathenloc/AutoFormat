// Keep legacy task links and their empty-session state intact.
const params = new URLSearchParams(location.hash.slice(1));
if (!params.has('task') && /^[A-Za-z0-9_-]{32,200}$/.test(params.get('session') ?? '')) await import('./home');
else await import('./main');
export {};
