#!/usr/bin/env node
// Print the keyed hash of a Patreon user id, as stored in PATREON_DB and as used by the
// `override_user_hmacs` map of ENTITLEMENT_POLICY (e.g. to grant your OWN creator account
// the seamless_updates capability, since a creator is not a member of their own campaign).
//
//   PATREON_ID_PEPPER=<the production pepper> node scripts/patreon-id-hmac.mjs <patreon_user_id>
//   node scripts/patreon-id-hmac.mjs <patreon_user_id> --pepper-env MY_OTHER_VAR
//
// hash = HMAC-SHA256(pepper, "patreon:" + patreon_user_id) as lowercase hex - identical to
// src/patreon/crypto.ts userHmac(). The pepper is read from an environment variable only, is never
// accepted on the command line and is never printed. Use the pepper of the SAME environment
// (staging / production) whose ENTITLEMENT_POLICY you are editing.
//
// Your Patreon user id: https://www.patreon.com/api/oauth2/v2/identity with a token of your own
// account (the numeric `data.id`), or the numeric id shown in your creator profile URL / API client.
import { createHmac } from "node:crypto";
import { fileURLToPath } from "node:url";

export function patreonIdHmac(pepper, userId) {
  return createHmac("sha256", pepper).update(`patreon:${userId}`, "utf8").digest("hex");
}

function main(argv) {
  let envName = "PATREON_ID_PEPPER";
  let userId = null;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--pepper-env") envName = argv[++i] ?? "";
    else if (a.startsWith("--")) throw new Error(`Unknown flag ${a}`);
    else if (userId === null) userId = a;
    else throw new Error(`Unexpected argument ${a}`);
  }
  if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(envName)) throw new Error("--pepper-env must be an environment variable name");
  if (userId === null || !/^[0-9]{1,20}$/.test(userId)) throw new Error("usage: node scripts/patreon-id-hmac.mjs <numeric patreon user id> [--pepper-env NAME]");
  const pepper = process.env[envName];
  if (typeof pepper !== "string" || pepper.length < 16) {
    throw new Error(`Set the pepper in the environment variable ${envName} (at least 16 characters). It is never printed.`);
  }
  console.log(patreonIdHmac(pepper, userId));
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    main(process.argv.slice(2));
  } catch (err) {
    process.stderr.write(`${err.message}\n`);
    process.exitCode = 1;
  }
}
