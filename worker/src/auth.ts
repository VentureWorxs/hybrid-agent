import { createRemoteJWKSet, jwtVerify } from "jose";

const JWKS_CACHE: Map<string, ReturnType<typeof createRemoteJWKSet>> = new Map();

function getJWKS(teamDomain: string) {
  if (!JWKS_CACHE.has(teamDomain)) {
    const jwksUri = new URL(`https://${teamDomain}/cdn-cgi/access/certs`);
    JWKS_CACHE.set(teamDomain, createRemoteJWKSet(jwksUri));
  }
  return JWKS_CACHE.get(teamDomain)!;
}

export async function validateAccessJwt(
  jwt: string,
  expectedAud: string,
  teamDomain: string = "nicheworxs.cloudflareaccess.com"
): Promise<boolean> {
  try {
    const jwks = getJWKS(teamDomain);
    await jwtVerify(jwt, jwks, { audience: expectedAud });
    return true;
  } catch {
    return false;
  }
}
