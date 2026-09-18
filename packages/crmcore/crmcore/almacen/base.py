"""Implementación del almacén. Ver el porqué en `crmcore/almacen/__init__.py`."""

from __future__ import annotations

from pathlib import Path
from threading import Lock
from typing import Protocol
from urllib.parse import urlparse

from crmcore.logging import get_logger

logger = get_logger(__name__)


class Almacen(Protocol):
    """Lo que cualquier backend tiene que saber hacer."""

    def guardar(self, clave: str, datos: bytes) -> str: ...
    def guardar_fichero(self, clave: str, origen: Path) -> str: ...
    def leer(self, uri: str) -> bytes: ...
    def borrar(self, uri: str) -> None: ...
    def existe(self, uri: str) -> bool: ...
    def tamano(self, uri: str) -> int: ...
    def leer_rango(self, uri: str, *, inicio: int, fin: int) -> bytes: ...
    def uri_de(self, clave: str) -> str: ...
    def ruta_para_leer(self, uri: str) -> Path | None: ...
    def borrar_prefijo(self, prefijo: str) -> int: ...


class AlmacenLocal:
    """Ficheros en disco, bajo una base fija.

    Para desarrollo y para instalaciones de un solo nodo. En cuanto hay más de
    una réplica deja de servir —cada una vería solo lo suyo— y por eso el
    arranque avisa si se usa con `ENV=prod`.
    """

    def __init__(self, base: Path) -> None:
        self.base = Path(base).resolve()
        self.base.mkdir(parents=True, exist_ok=True)

    def _bajo_base(self, relativa: str, *, sujeto: str) -> Path:
        """**Único** guard de path traversal de esta clase.

        `resolve()` sigue enlaces simbólicos a propósito: un symlink dentro de
        la base que apunte fuera se resuelve fuera y se rechaza.
        """
        resuelta = (self.base / relativa).resolve()
        if not resuelta.is_relative_to(self.base):
            raise ValueError(f"clave insegura (path traversal): {sujeto}")
        return resuelta

    def _clave_de_uri(self, uri: str) -> str:
        partes = urlparse(uri)
        if partes.scheme != "local":
            raise ValueError(f"URI que no es de este almacén: {uri}")
        return f"{partes.netloc}{partes.path}".lstrip("/")

    def _ruta(self, uri: str) -> Path:
        return self._bajo_base(self._clave_de_uri(uri), sujeto=uri)

    def guardar(self, clave: str, datos: bytes) -> str:
        # Validar ANTES del mkdir: si no, una clave con `..` crea directorios
        # fuera de la base antes de fallar, que es un efecto observable desde
        # fuera aunque nunca se llegue a escribir el fichero.
        destino = self._bajo_base(clave, sujeto=clave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(datos)
        return self.uri_de(clave)

    def guardar_fichero(self, clave: str, origen: Path) -> str:
        """Mueve un fichero ya existente SIN cargarlo en memoria."""
        import shutil

        destino = self._bajo_base(clave, sujeto=clave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(origen), str(destino))
        return self.uri_de(clave)

    def leer(self, uri: str) -> bytes:
        return self._ruta(uri).read_bytes()

    def borrar(self, uri: str) -> None:
        destino = self._ruta(uri)
        if destino.exists():
            destino.unlink()
        padre = destino.parent
        while padre != self.base and padre.exists() and not any(padre.iterdir()):
            try:
                padre.rmdir()
            except OSError:
                # Otra escritura aterrizó entre el `iterdir` y el `rmdir`. El
                # borrado del fichero ya salió bien; los directorios los limpiará
                # el siguiente.
                break
            padre = padre.parent

    def existe(self, uri: str) -> bool:
        try:
            return self._ruta(uri).exists()
        except ValueError:
            return False

    def tamano(self, uri: str) -> int:
        return self._ruta(uri).stat().st_size

    def leer_rango(self, uri: str, *, inicio: int, fin: int) -> bytes:
        if inicio < 0 or fin < inicio:
            raise ValueError("rango de bytes inválido")
        with self._ruta(uri).open("rb") as f:
            f.seek(inicio)
            return f.read(fin - inicio + 1)

    def uri_de(self, clave: str) -> str:
        return f"local://{clave.lstrip('/')}"

    def ruta_para_leer(self, uri: str) -> Path | None:
        try:
            ruta = self._ruta(uri)
        except ValueError:
            raise
        return ruta if ruta.exists() and ruta.is_file() else None

    def borrar_prefijo(self, prefijo: str) -> int:
        """Borra todo lo que cuelgue de un prefijo. Devuelve cuántos ficheros.

        Pasa por el MISMO guard de path traversal que el resto: un prefijo con
        `..` borraría fuera de la base, y de todas las operaciones de esta clase
        esta es en la que equivocarse es irreversible.
        """
        import shutil

        objetivo = self._bajo_base(prefijo, sujeto=prefijo)
        if not objetivo.exists() or not objetivo.is_dir():
            return 0
        borrados = sum(1 for f in objetivo.rglob("*") if f.is_file())
        shutil.rmtree(objetivo)
        return borrados


class AlmacenS3:
    """Cualquier almacén compatible con S3: AWS, MinIO, Ceph, Backblaze.

    Genérico a propósito (`endpoint_url` configurable): no hay un conector por
    proveedor, hay un protocolo y una configuración.
    """

    def __init__(
        self,
        *,
        bucket: str,
        prefijo: str = "",
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        usar_ssl: bool = True,
        estilo_ruta: bool = False,
    ) -> None:
        if not bucket.strip():
            raise ValueError("Falta el bucket: es obligatorio con STORAGE_BACKEND=s3")
        try:
            import boto3
            from botocore.config import Config as BotoConfig
        except ImportError as exc:  # pragma: no cover — depende del entorno
            raise RuntimeError(
                "El backend s3 necesita boto3. Instálalo o usa STORAGE_BACKEND=local."
            ) from exc

        self.bucket = bucket.strip()
        self.prefijo = prefijo.strip("/")
        self._cliente = boto3.session.Session().client(
            "s3",
            region_name=region or None,
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id or None,
            aws_secret_access_key=secret_access_key or None,
            use_ssl=bool(usar_ssl),
            # `path` hace falta con MinIO y con la mayoría de compatibles: el
            # estilo por subdominio exige DNS comodín, que casi nadie monta.
            config=BotoConfig(s3={"addressing_style": "path" if estilo_ruta else "auto"}),
        )

    def _clave_completa(self, clave: str) -> str:
        limpia = clave.lstrip("/")
        return f"{self.prefijo}/{limpia}" if self.prefijo else limpia

    def _partes(self, uri: str) -> tuple[str, str]:
        p = urlparse(uri)
        if p.scheme != "s3":
            raise ValueError(f"URI que no es de este almacén: {uri}")
        return p.netloc, p.path.lstrip("/")

    def guardar(self, clave: str, datos: bytes) -> str:
        completa = self._clave_completa(clave)
        self._cliente.put_object(Bucket=self.bucket, Key=completa, Body=datos)
        return f"s3://{self.bucket}/{completa}"

    def guardar_fichero(self, clave: str, origen: Path) -> str:
        completa = self._clave_completa(clave)
        self._cliente.upload_file(str(origen), self.bucket, completa)
        return f"s3://{self.bucket}/{completa}"

    def leer(self, uri: str) -> bytes:
        bucket, clave = self._partes(uri)
        return self._cliente.get_object(Bucket=bucket, Key=clave)["Body"].read()

    def borrar(self, uri: str) -> None:
        bucket, clave = self._partes(uri)
        self._cliente.delete_object(Bucket=bucket, Key=clave)

    def existe(self, uri: str) -> bool:
        from botocore.exceptions import ClientError

        bucket, clave = self._partes(uri)
        try:
            self._cliente.head_object(Bucket=bucket, Key=clave)
            return True
        except ClientError:
            return False

    def tamano(self, uri: str) -> int:
        bucket, clave = self._partes(uri)
        return int(self._cliente.head_object(Bucket=bucket, Key=clave)["ContentLength"])

    def leer_rango(self, uri: str, *, inicio: int, fin: int) -> bytes:
        if inicio < 0 or fin < inicio:
            raise ValueError("rango de bytes inválido")
        bucket, clave = self._partes(uri)
        respuesta = self._cliente.get_object(
            Bucket=bucket, Key=clave, Range=f"bytes={inicio}-{fin}"
        )
        return respuesta["Body"].read()

    def uri_de(self, clave: str) -> str:
        return f"s3://{self.bucket}/{self._clave_completa(clave)}"

    def ruta_para_leer(self, uri: str) -> Path | None:
        # En S3 no hay ruta local; quien sirve el fichero lo hace por stream.
        return None

    def borrar_prefijo(self, prefijo: str) -> int:
        """Borra un prefijo entero, paginando y en lotes de mil.

        Paginado porque `list_objects_v2` devuelve como mucho mil claves por
        llamada y quedarse con la primera página dejaría la mayor parte del
        prefijo sin borrar — con el agravante de que la operación informaría de
        éxito. Un tenant grande tiene decenas de miles de ficheros.
        """
        completo = self._clave_completa(prefijo).rstrip("/") + "/"
        borrados = 0
        paginador = self._cliente.get_paginator("list_objects_v2")
        for pagina in paginador.paginate(Bucket=self.bucket, Prefix=completo):
            claves = [{"Key": o["Key"]} for o in pagina.get("Contents", [])]
            if not claves:
                continue
            self._cliente.delete_objects(Bucket=self.bucket, Delete={"Objects": claves})
            borrados += len(claves)
        return borrados


_almacen: Almacen | None = None
_cerrojo = Lock()


def get_almacen() -> Almacen:
    """Almacén configurado, construido una sola vez por proceso.

    Con doble comprobación bajo cerrojo: construir el cliente de S3 abre una
    sesión, y con varios hilos de Uvicorn atendiendo la primera subida a la vez
    se crearían varios y se quedaría uno al azar.
    """
    global _almacen
    if _almacen is not None:
        return _almacen
    with _cerrojo:
        if _almacen is not None:
            return _almacen
        from crmcore.config import get_settings

        s = get_settings()
        if s.storage_backend == "s3":
            _almacen = AlmacenS3(
                bucket=s.storage_s3_bucket,
                prefijo=s.storage_s3_prefijo,
                region=s.storage_s3_region or None,
                endpoint_url=s.storage_s3_endpoint or None,
                access_key_id=s.storage_s3_access_key or None,
                secret_access_key=(
                    s.storage_s3_secret_key.get_secret_value() if s.storage_s3_secret_key else None
                ),
                usar_ssl=s.storage_s3_ssl,
                estilo_ruta=s.storage_s3_estilo_ruta,
            )
        else:
            _almacen = AlmacenLocal(Path(s.storage_local_path))
        logger.info("almacen.listo", backend=s.storage_backend)
        return _almacen


def reset_almacen() -> None:
    """Olvida el almacén cacheado. Solo para pruebas y para el sembrador."""
    global _almacen
    with _cerrojo:
        _almacen = None


def purgar_tenant(tenant_id: str) -> int:
    """Borra del almacén TODOS los ficheros de un tenant (CRM-00.01.01.08).

    Es lo que hace que la baja de un cliente sea de verdad. Funciona porque cada
    clave se construye con el tenant delante (`<tenant>/<hash>/…`): sin ese
    prefijo obligatorio, dar de baja a un cliente exigiría recorrer la tabla de
    adjuntos, y lo que no estuviera en la tabla —un huérfano, un resto de una
    migración— se quedaría en el almacén para siempre.

    Irreversible y sin papelera: quien llama tiene que haberlo decidido. Se
    registra con el recuento, que es la única prueba de qué se destruyó.
    """
    borrados = get_almacen().borrar_prefijo(str(tenant_id))
    logger.warning(
        "almacen.tenant_purgado",
        tenant=str(tenant_id),
        ficheros=borrados,
        aviso="borrado definitivo, sin papelera",
    )
    return borrados
