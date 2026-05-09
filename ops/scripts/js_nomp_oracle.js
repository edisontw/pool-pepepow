#!/usr/bin/env node
"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");

const TARGET_ROWS = [
  {
    label: "Selected rejected row",
    jobId: "job-000000000000000e",
    extranonce2: "29a376a8",
    ntime: "69f9e717",
    nonce: "5057dabe",
  },
  {
    label: "Selected accepted row",
    jobId: "job-000000000000000f",
    extranonce2: "11a776a8",
    ntime: "69f9e726",
    nonce: "d16caa81",
  },
];

function usage() {
  console.error(
    "usage: js_nomp_oracle.js <miner-log> <tail-lines> <submit-tail> <notify-tail> <nomp-root>"
  );
}

function normHex(value) {
  if (typeof value !== "string") {
    return null;
  }
  const out = value.trim().toLowerCase();
  return /^[0-9a-f]+$/.test(out) ? out : null;
}

function readJsonLines(filePath) {
  return fs
    .readFileSync(filePath, "utf8")
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      try {
        const parsed = JSON.parse(line);
        return parsed && typeof parsed === "object" ? parsed : null;
      } catch (_err) {
        return null;
      }
    })
    .filter(Boolean);
}

function parseMinerLog(filePath) {
  const lines = fs.readFileSync(filePath, "utf8").split(/\r?\n/);
  const rows = [];
  let lastSolution = null;

  const solutionRe =
    /PEPEW job (\S+) solution found! nonce=(\d+) xnonce2=(\d+) hash=([0-9a-fA-F]{64})/;
  const submitRe =
    /"method":\s*"mining\.submit",\s*"params":\s*\[\s*"[^"]*",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)",\s*"([^"]+)"/;

  for (const line of lines) {
    const solutionMatch = line.match(solutionRe);
    if (solutionMatch) {
      lastSolution = {
        jobId: solutionMatch[1],
        nonceHex: Number(solutionMatch[2]).toString(16).padStart(8, "0"),
        extranonce2Hex: Number(solutionMatch[3]).toString(16).padStart(8, "0"),
        minerReportedHash: solutionMatch[4].toLowerCase(),
      };
      continue;
    }

    const submitMatch = line.match(submitRe);
    if (submitMatch) {
      const row = {
        jobId: submitMatch[1],
        extranonce2: submitMatch[2].toLowerCase(),
        ntime: submitMatch[3].toLowerCase(),
        nonce: submitMatch[4].toLowerCase(),
        minerReportedHash: null,
      };
      if (lastSolution && lastSolution.jobId === row.jobId && lastSolution.nonceHex === row.nonce) {
        row.minerReportedHash = lastSolution.minerReportedHash;
      }
      rows.push(row);
    }
  }
  return rows;
}

function evidenceKey(row) {
  return [
    row.jobId || "",
    normHex(row.extranonce2) || "",
    normHex(row.ntime) || "",
    normHex(row.nonce) || "",
  ].join("|");
}

function reverseHexBytes(hex) {
  const raw = Buffer.from(hex, "hex");
  return Buffer.from(raw).reverse().toString("hex");
}

function parseTargetInt(hex) {
  const value = normHex(hex);
  return value ? BigInt("0x" + value) : null;
}

function hashMeetsTarget(hashHex, targetHex) {
  const hash = normHex(hashHex);
  const target = parseTargetInt(targetHex);
  if (!hash || target === null) {
    return null;
  }
  return BigInt("0x" + hash) <= target;
}

function selectExactRow(rows, target) {
  return (
    rows.find(
      (row) =>
        row.jobId === target.jobId &&
        normHex(row.extranonce2) === target.extranonce2 &&
        normHex(row.ntime) === target.ntime &&
        normHex(row.nonce) === target.nonce
    ) || null
  );
}

function reverseBufferCopy(buf) {
  return Buffer.from(buf).reverse();
}

function sha256(buffer) {
  return crypto.createHash("sha256").update(buffer).digest();
}

function sha256d(buffer) {
  return sha256(sha256(buffer));
}

function reverseBuffer(buffer) {
  return reverseBufferCopy(buffer);
}

function serializeHeaderLikeNomp(rpcData, merkleRootRevHex, nTimeHex, nonceHex) {
  let header = Buffer.alloc(80);
  let position = 0;
  header.write(nonceHex, position, 4, "hex");
  header.write(rpcData.bits, (position += 4), 4, "hex");
  header.write(nTimeHex, (position += 4), 4, "hex");
  header.write(merkleRootRevHex, (position += 4), 32, "hex");
  header.write(rpcData.previousblockhash, (position += 32), 32, "hex");
  header.writeUInt32BE(rpcData.version >>> 0, position + 32);
  header = reverseBuffer(header);
  return header;
}

function withFirstLikeMerkleTree(first, branches) {
  let root = Buffer.from(first);
  for (const branchHex of Array.isArray(branches) ? branches : []) {
    const branch = Buffer.from(branchHex, "hex");
    root = sha256d(Buffer.concat([root, branch]));
  }
  return root;
}

function buildOracleRow(target, minerRow, submitRow, notifyRow, multiHashing) {
  if (!submitRow) {
    return { label: target.label, error: "submit evidence row not found in bounded tail" };
  }
  if (!notifyRow) {
    return { label: target.label, error: "notify evidence row not found in bounded tail" };
  }
  if (!minerRow || !minerRow.minerReportedHash) {
    return { label: target.label, error: "miner log pair not found for exact submit" };
  }

  const extranonce1 = normHex(submitRow.extranonce1);
  const extranonce2 = normHex(submitRow.extranonce2);
  const coinb1 = normHex(submitRow.issuedJobCoinb1);
  const coinb2 = normHex(submitRow.issuedJobCoinb2);
  const ntime = normHex(submitRow.submitNtimeUsed || submitRow.ntime);
  const nonce = normHex(submitRow.nonce);
  const bits = normHex(submitRow.submitNbitsUsed || submitRow.notifyNbitsSent || submitRow.preimageNbits);
  const versionHex = normHex(
    submitRow.submitVersionUsed || submitRow.notifyVersionSent || submitRow.preimageVersion
  );
  const prevhashHex = normHex(submitRow.submitPrevhashCached || submitRow.preimagePrevhash);

  if (!extranonce1 || !extranonce2 || !coinb1 || !coinb2 || !ntime || !nonce || !bits || !versionHex || !prevhashHex) {
    return { label: target.label, error: "missing required submit evidence fields" };
  }

  const coinbaseHex = coinb1 + extranonce1 + extranonce2 + coinb2;
  const coinbase = Buffer.from(coinbaseHex, "hex");
  const coinbaseHash = sha256d(coinbase);
  const merkleRoot = withFirstLikeMerkleTree(
    coinbaseHash,
    submitRow.issuedJobMerkleBranch || notifyRow.merkleBranch || []
  );
  const merkleRootRevHex = reverseBuffer(merkleRoot).toString("hex");
  const rpcData = {
    previousblockhash: prevhashHex,
    bits: bits,
    version: parseInt(versionHex, 16) >>> 0,
  };
  const header80 = serializeHeaderLikeNomp(rpcData, merkleRootRevHex, ntime, nonce);
  const hoohashRaw = multiHashing.hoohashv110(header80);
  const jsHash = hoohashRaw.toString("hex");
  const jsHashReversed = reverseBufferCopy(hoohashRaw).toString("hex");
  const shareTarget = normHex(submitRow.shareTargetUsed || submitRow.shareTarget);
  const localHash = normHex(submitRow.localComputedHash);
  const localHeader = normHex(submitRow.header80Hex);

  return {
    label: target.label,
    jobId: submitRow.jobId,
    extranonce1,
    extranonce2,
    ntime,
    nonce,
    poolStatus:
      submitRow.shareHashValidationStatus === "share-hash-valid"
        ? "accepted"
        : submitRow.rejectReason || "rejected",
    minerReportedHash: minerRow.minerReportedHash,
    pythonPoolLocalComputedHash: localHash,
    pythonPoolHeader80Hex: localHeader,
    jsNompCoinbaseHex: coinbaseHex,
    jsNompMerkleRoot: merkleRoot.toString("hex"),
    jsNompMerkleRootReversed: merkleRootRevHex,
    jsNompHeader80Hex: header80.toString("hex"),
    jsNompHoohashRaw: jsHash,
    jsNompHoohashReversed: jsHashReversed,
    jsNompHashMatchesMiner: jsHash === minerRow.minerReportedHash,
    reversedJsNompHashMatchesMiner: jsHashReversed === minerRow.minerReportedHash,
    jsNompHashMeetsShareTarget: hashMeetsTarget(jsHash, shareTarget),
    localComputedHashMeetsShareTarget:
      typeof submitRow.meetsShareTarget === "boolean"
        ? submitRow.meetsShareTarget
        : hashMeetsTarget(localHash, shareTarget),
    jsNompHeaderDiffersFromPythonPoolHeader:
      localHeader ? header80.toString("hex") !== localHeader : null,
    shareTarget,
    exactDifferenceVsPythonPool: {
      coinbaseHexDiffers:
        normHex(submitRow.coinbaseLocalHex) ? normHex(submitRow.coinbaseLocalHex) !== coinbaseHex : null,
      merkleRootDiffers:
        normHex(submitRow.merkleRoot) ? normHex(submitRow.merkleRoot) !== merkleRoot.toString("hex") : null,
      header80Differs:
        localHeader ? localHeader !== header80.toString("hex") : null,
      prevhashTransformDiffers:
        normHex(submitRow.preimagePrevhash) ? normHex(submitRow.preimagePrevhash) !== prevhashHex : null,
      versionBytesDiffers:
        normHex(submitRow.preimageVersion) ? normHex(submitRow.preimageVersion) !== versionHex : null,
      ntimeBytesDiffers:
        normHex(submitRow.preimageJobNtime || submitRow.submitNtimeUsed) ? normHex(submitRow.preimageJobNtime || submitRow.submitNtimeUsed) !== ntime : null,
      nbitsBytesDiffers:
        normHex(submitRow.preimageNbits || submitRow.submitNbitsUsed) ? normHex(submitRow.preimageNbits || submitRow.submitNbitsUsed) !== bits : null,
      nonceBytesDiffers: false,
    },
  };
}

function printKv(name, value) {
  if (typeof value === "boolean") {
    console.log(`${name}: ${value ? "yes" : "no"}`);
    return;
  }
  if (value === null || value === undefined) {
    console.log(`${name}: -`);
    return;
  }
  if (typeof value === "object") {
    console.log(`${name}: ${JSON.stringify(value)}`);
    return;
  }
  console.log(`${name}: ${value}`);
}

function main(argv) {
  if (argv.length !== 7) {
    usage();
    return 1;
  }

  const minerLog = path.resolve(argv[2]);
  const tailLines = argv[3];
  const submitTailPath = path.resolve(argv[4]);
  const notifyTailPath = path.resolve(argv[5]);
  const nompRoot = path.resolve(argv[6]);

  const multiHashing = require(path.join(nompRoot, "node_modules/multi-hashing"));

  const minerRows = parseMinerLog(minerLog);
  const submitRows = readJsonLines(submitTailPath);
  const notifyRows = readJsonLines(notifyTailPath);
  const submitByKey = new Map(submitRows.map((row) => [evidenceKey(row), row]));
  const notifyByJob = new Map(notifyRows.map((row) => [row.jobId, row]));
  const minerByKey = new Map(minerRows.map((row) => [evidenceKey(row), row]));

  console.log("Summary");
  printKv("js_nomp_oracle", "ready");
  printKv("minerLog", minerLog);
  printKv("boundedTailLines", tailLines);
  printKv("submitEvidenceRowsRead", submitRows.length);
  printKv("notifyEvidenceRowsRead", notifyRows.length);
  printKv("minerSubmitPairsRead", minerRows.length);
  printKv("nompRoot", nompRoot);
  printKv(
    "multiHashingModule",
    require.resolve(path.join(nompRoot, "node_modules/multi-hashing"))
  );
  console.log("");

  for (const target of TARGET_ROWS) {
    const key = evidenceKey(target);
    const result = buildOracleRow(
      target,
      minerByKey.get(key) || null,
      submitByKey.get(key) || null,
      notifyByJob.get(target.jobId) || null,
      multiHashing
    );
    console.log(result.label);
    if (result.error) {
      printKv("error", result.error);
      console.log("");
      continue;
    }
    printKv("selectedRowIdentity", `${result.jobId} ${result.extranonce2} ${result.ntime} ${result.nonce}`);
    printKv("poolStatus", result.poolStatus);
    printKv("minerReportedHash", result.minerReportedHash);
    printKv("pythonPoolLocalComputedHash", result.pythonPoolLocalComputedHash);
    printKv("pythonPoolHeader80Hex", result.pythonPoolHeader80Hex);
    printKv("jsNompHeader80Hex", result.jsNompHeader80Hex);
    printKv("jsNompHoohashRaw", result.jsNompHoohashRaw);
    printKv("jsNompHoohashReversed", result.jsNompHoohashReversed);
    printKv("jsNompHash == minerReportedHash", result.jsNompHashMatchesMiner);
    printKv("reversedJsNompHash == minerReportedHash", result.reversedJsNompHashMatchesMiner);
    printKv("jsNompHash meets share target", result.jsNompHashMeetsShareTarget);
    printKv("localComputedHash meets share target", result.localComputedHashMeetsShareTarget);
    printKv("jsNompHeader differs from Python pool header", result.jsNompHeaderDiffersFromPythonPoolHeader);
    printKv("jsNompCoinbaseHex", result.jsNompCoinbaseHex);
    printKv("jsNompMerkleRoot", result.jsNompMerkleRoot);
    printKv("jsNompMerkleRootReversed", result.jsNompMerkleRootReversed);
    printKv("shareTarget", result.shareTarget);
    printKv("exactDifferenceVsPythonPool", result.exactDifferenceVsPythonPool);
    console.log("");
  }

  return 0;
}

process.exitCode = main(process.argv);
