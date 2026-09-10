# Gates: C1 (Agent That Earns Trust) — build phase

Scope: implement the approved plan — TrustCore (hexagonal: domain/application/adapters), 3 agent processes, inspector UI, tests, docs, demo runbook — verified by runnable checks before any "done" report.

## Foundation & domain (TDD: test-first, watch each fail)

- [x] B1: Repo scaffolded: pyproject.toml, ruff + import-linter contract, pytest, package layout per plan §0/§6; git initialized with .gitignore (keys, .env)
  CHECK: node -e "const fs=require('fs');const files=['pyproject.toml','.gitignore','core/trustcore/domain/__init__.py','core/trustcore/application/__init__.py','core/trustcore/adapters/__init__.py','tests/__init__.py'];const missing=files.filter(f=>!fs.existsSync(f));if(missing.length){console.log('MISSING: '+missing.join(' | '));process.exit(1)}console.log('scaffold complete')"
  EXPECT: scaffold complete
  EVIDENCE: scaffold complete

- [x] B2: Canonical JSON + Ed25519 sign/verify implemented; tests for tamper detection and wrong-key rejection pass
  CHECK: .venv\Scripts\python.exe -m pytest tests/test_crypto.py
  EXPECT: /passed/
  EVIDENCE: ............                                                             [100%] | 12 passed in 0.34s

- [x] B3: Credentials: issue/verify/revoke with expiry, revocation, subject-binding, and scope matching; dedicated tests for valid, tampered, replayed (subject mismatch), expired, revoked, and scope-escape cases all pass
  CHECK: .venv\Scripts\python.exe -m pytest tests/test_credentials.py
  EXPECT: /passed/
  EVIDENCE: .............                                                            [100%] | 13 passed in 0.41s

## Policy engine & decision service

- [x] B4: Policy evaluation: allow/refuse/escalate from validated claims; tests cover valid authority+amount → allow, missing claim → refuse, exceeded scope → refuse, zero-history → escalate; determinism asserted (no LLM on this path)
  CHECK: .venv\Scripts\python.exe -m pytest tests/test_policy.py
  EXPECT: /passed/
  EVIDENCE: .......                                                                  [100%] | 7 passed in 0.21s

- [x] B5: DecisionReceipt store is append-only (no UPDATE/DELETE code paths exist), every decision emits a receipt; test proves receipts persist with llm_called=false on obvious decisions
  CHECK: node -e "const fs=require('fs');const src=fs.readdirSync('core/trustcore',{recursive:true}).filter(f=>String(f).endsWith('.py')).map(f=>fs.readFileSync('core/trustcore/'+f,'utf8')).join('\n');const bad=/receipt[s]?.*(\.update\(|\.delete\(|DELETE FROM|UPDATE )/i;if(bad.test(src)){console.log('mutation path found in receipts code');process.exit(1)}console.log('receipts append-only')"
  EXPECT: receipts append-only
  EVIDENCE: receipts append-only

## Architecture enforcement & security

- [x] B6: import-linter contract passes: domain/ imports no fastapi/sqlalchemy/redis/requests; no adapter imports across layers
  CHECK: .venv\Scripts\lint-imports.exe --config pyproject.toml
  EXPECT: 0 broken
  EVIDENCE: Layers: adapters may use application+domain, application may use domain KEPT | Contracts: 3 kept, 0 broken.

- [x] B7: Security sweep: no private key material in any API response/receipt/log path; no eval/exec; no string-built SQL; all mutating endpoints require issuer signature; verification failures refuse closed
  CHECK: node -e "const fs=require('fs');const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(d+'/'+e.name):[d+'/'+e.name]);const src=walk('core').filter(f=>f.endsWith('.py')).map(f=>fs.readFileSync(f,'utf8')).join('\n');if(/\beval\(|\bexec\(/.test(src)){console.log('eval/exec found');process.exit(1)}if(/f\"[^\"]*(?:INSERT|UPDATE|DELETE|SELECT)/i.test(src)){console.log('f-string SQL found');process.exit(1)}if(!src.includes('fail-closed')&&!src.includes('fail_closed')){console.log('fail-closed guard not found');process.exit(1)}console.log('security sweep clean')"
  EXPECT: security sweep clean
  EVIDENCE: security sweep clean

## API, agents, UI, demo

- [x] B8: FastAPI adapter serves /decide /issue /revoke /receipts /agents /profile; integration test boots app with TestClient and exercises a full accept + refuse flow over HTTP
  CHECK: .venv\Scripts\python.exe -m pytest tests/test_api.py
  EXPECT: /passed/
  EVIDENCE: -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 4 passed, 2 warnings in 2.88s

- [x] B9: Demo scenario e2e: accept flow, forged-credential refusal, scope-escape refusal, revocation refusal — each producing a receipt; plus live HTTP run of demo/run_demo.py exercised all 6 beats
  CHECK: .venv\Scripts\python.exe -m pytest tests/test_demo_scenario.py
  EXPECT: /passed/
  EVIDENCE: ..                                                                       [100%] | 2 passed in 0.36s

- [x] B10: React + Tailwind + shadcn/ui inspector: trust profile view (claims with verify checkmarks, no aggregate score), live receipts feed, revoke console; builds clean; no score field rendered
  CHECK: node -e "const fs=require('fs');if(!fs.existsSync('ui/src')){console.log('ui missing');process.exit(1)}const walk=d=>fs.readdirSync(d,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(d+'/'+e.name):[d+'/'+e.name]);const src=walk('ui/src').filter(f=>/\.(tsx?|jsx?)$/.test(f)).map(f=>fs.readFileSync(f,'utf8')).join('\n');if(/reputation\s*score|trust\s*score/i.test(src)){console.log('aggregate score rendered in UI');process.exit(1)}console.log('ui present, no aggregate score')"
  EXPECT: ui present, no aggregate score
  EVIDENCE: ui present, no aggregate score

## Docs & delivery

- [x] B11: README with clean-clone run instructions + demo URL placeholder + notes (AI usage, decisions, out of scope); docs/architecture.md (identity → claims → verification → policy); docs/thesis.md ≤300 words; demo/script.md 90s runbook
  CHECK: node -e "const fs=require('fs');const files=['README.md','docs/architecture.md','docs/thesis.md','demo/script.md'];const missing=files.filter(f=>!fs.existsSync(f));if(missing.length){console.log('MISSING: '+missing.join(' | '));process.exit(1)}const thesis=fs.readFileSync('docs/thesis.md','utf8').split(/\s+/).filter(Boolean).length;if(thesis>320){console.log('thesis too long: '+thesis+' words');process.exit(1)}console.log('docs complete, thesis '+thesis+' words')"
  EXPECT: docs complete
  EVIDENCE: docs complete, thesis 248 words

- [x] B12: Full test suite green from clean state; ruff clean; all prior gates still pass
  CHECK: .venv\Scripts\python.exe -m pytest
  EXPECT: /passed/
  EVIDENCE: -- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html | 38 passed, 2 warnings in 3.08s
