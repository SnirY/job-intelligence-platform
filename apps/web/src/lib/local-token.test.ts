import { describe, expect, it } from "vitest";

import { mintLocalToken, verifyLocalToken } from "@/lib/local-token";

/**
 * The frontend mints these and the API verifies them, so the two
 * implementations have to agree on a format neither one owns. These tests hold
 * this half: shape, signature, and expiry.
 */

const SECRET = "x".repeat(32);
const OTHER_SECRET = "y".repeat(32);

describe("local token", () => {
  it("round-trips a subject", () => {
    const token = mintLocalToken(SECRET, { sub: "demo" });

    expect(verifyLocalToken(SECRET, token)).toBe("demo");
  });

  it("is a three-part JWS carrying HS256 in its header", () => {
    const [header, , signature] = mintLocalToken(SECRET, { sub: "demo" }).split(".");

    expect(signature).toBeTruthy();
    expect(JSON.parse(Buffer.from(header!, "base64url").toString())).toEqual({
      alg: "HS256",
      typ: "JWT",
    });
  });

  it("carries the claims the API reads", () => {
    const [, payload] = mintLocalToken(SECRET, { sub: "demo", name: "Demo" }).split(".");

    const claims = JSON.parse(Buffer.from(payload!, "base64url").toString());

    expect(claims).toMatchObject({ sub: "demo", name: "Demo" });
    expect(claims.exp).toBeGreaterThan(claims.iat);
  });

  it("refuses a token signed with another secret", () => {
    const token = mintLocalToken(OTHER_SECRET, { sub: "demo" });

    expect(verifyLocalToken(SECRET, token)).toBeNull();
  });

  it("refuses a token whose payload was edited after signing", () => {
    const [header, , signature] = mintLocalToken(SECRET, { sub: "demo" }).split(".");
    const forged = Buffer.from(
      JSON.stringify({ sub: "someone-else", exp: Math.floor(Date.now() / 1000) + 3600 }),
    ).toString("base64url");

    expect(verifyLocalToken(SECRET, `${header}.${forged}.${signature}`)).toBeNull();
  });

  it("refuses an expired token", () => {
    const token = mintLocalToken(SECRET, { sub: "demo" }, -3600);

    expect(verifyLocalToken(SECRET, token)).toBeNull();
  });

  it("refuses anything that is not a three-part token", () => {
    expect(verifyLocalToken(SECRET, "")).toBeNull();
    expect(verifyLocalToken(SECRET, "not.a.token.at.all")).toBeNull();
    expect(verifyLocalToken(SECRET, "onlyonepart")).toBeNull();
  });
});
