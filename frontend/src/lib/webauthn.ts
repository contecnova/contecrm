/**
 * Passkeys en el navegador (CRM-00.05.01.23).
 *
 * Todo lo que hay aquí es traducir entre lo que manda el servidor —texto en
 * base64url, que es lo que viaja por JSON— y lo que pide el navegador, que son
 * `ArrayBuffer`. Ni una decisión de seguridad: esas las toma el servidor, que
 * es el único sitio donde se pueden tomar.
 */

/** ¿Este navegador sabe de passkeys? */
export function admitePasskeys(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.create === "function"
  );
}

function deBase64url(valor: string): Uint8Array {
  const normal = valor.replace(/-/g, "+").replace(/_/g, "/");
  const relleno = normal.padEnd(normal.length + ((4 - (normal.length % 4)) % 4), "=");
  const bruto = atob(relleno);
  const salida = new Uint8Array(bruto.length);
  for (let i = 0; i < bruto.length; i += 1) salida[i] = bruto.charCodeAt(i);
  return salida;
}

function aBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let texto = "";
  for (const b of bytes) texto += String.fromCharCode(b);
  return btoa(texto).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

interface OpcionesServidor {
  challenge: string;
  user?: { id: string; name: string; displayName: string };
  allowCredentials?: { id: string; type: string; transports?: string[] }[];
  excludeCredentials?: { id: string; type: string; transports?: string[] }[];
  [clave: string]: unknown;
}

function conBuffers(opciones: OpcionesServidor): Record<string, unknown> {
  const copia: Record<string, unknown> = { ...opciones, challenge: deBase64url(opciones.challenge) };
  if (opciones.user) copia.user = { ...opciones.user, id: deBase64url(opciones.user.id) };
  for (const lista of ["allowCredentials", "excludeCredentials"] as const) {
    const valores = opciones[lista];
    if (valores) copia[lista] = valores.map((c) => ({ ...c, id: deBase64url(c.id) }));
  }
  return copia;
}

/** Lo que devuelve el navegador, ya en el formato que espera el servidor. */
function comoJson(credencial: PublicKeyCredential): Record<string, unknown> {
  const r = credencial.response as AuthenticatorAttestationResponse &
    AuthenticatorAssertionResponse;
  const respuesta: Record<string, unknown> = {
    clientDataJSON: aBase64url(r.clientDataJSON),
  };
  if (r.attestationObject) respuesta.attestationObject = aBase64url(r.attestationObject);
  if (r.authenticatorData) respuesta.authenticatorData = aBase64url(r.authenticatorData);
  if (r.signature) respuesta.signature = aBase64url(r.signature);
  if (r.userHandle) respuesta.userHandle = aBase64url(r.userHandle);
  return {
    id: credencial.id,
    rawId: aBase64url(credencial.rawId),
    type: credencial.type,
    response: respuesta,
    clientExtensionResults: credencial.getClientExtensionResults(),
  };
}

/** Crea una llave nueva con las opciones que ha dado el servidor. */
export async function crearPasskey(opciones: OpcionesServidor): Promise<Record<string, unknown>> {
  const credencial = (await navigator.credentials.create({
    publicKey: conBuffers(opciones) as unknown as PublicKeyCredentialCreationOptions,
  })) as PublicKeyCredential | null;
  if (!credencial) throw new Error("El navegador no ha creado ninguna llave");
  return comoJson(credencial);
}

/** Firma el reto con una llave ya registrada. */
export async function firmarConPasskey(
  opciones: OpcionesServidor,
): Promise<Record<string, unknown>> {
  const credencial = (await navigator.credentials.get({
    publicKey: conBuffers(opciones) as unknown as PublicKeyCredentialRequestOptions,
  })) as PublicKeyCredential | null;
  if (!credencial) throw new Error("No se ha firmado con ninguna llave");
  return comoJson(credencial);
}
