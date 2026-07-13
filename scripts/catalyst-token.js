// Mint a Catalyst access token from the `catalyst login` the CLI already stores,
// so provisioning/seeding scripts need no OAuth client of their own.
//   CATALYST_ACCESS_TOKEN=$(node scripts/catalyst-token.js) python -m data.provision
const path = require('path');
const { execSync } = require('child_process');

const ROOT = path.join(
  execSync('npm root -g').toString().trim(),
  'zcatalyst-cli'
);
const LIB = path.join(ROOT, 'lib');

const store = require(path.join(LIB, 'runtime-store')).default;
const pkg = require(path.join(ROOT, 'package.json'));
store.set('cli.package.name', pkg.name);
store.set('cli.package.version', pkg.version);

const configStore = require(path.join(LIB, 'util_modules/config-store.js')).default;
const Credential = require(path.join(LIB, 'authentication/credential')).default;

const dc = configStore.get('active_dc') || 'in';
const token = configStore.get(`${dc}.credential`);
if (!token) {
  console.error(`No stored Catalyst login for DC "${dc}". Run: catalyst login`);
  process.exit(1);
}
store.set('credential', Credential.initToken(token, false));
Credential.getAccessToken(true).then(
  (t) => console.log(t),
  (e) => {
    console.error('Token refresh failed:', e.message);
    process.exit(1);
  }
);
