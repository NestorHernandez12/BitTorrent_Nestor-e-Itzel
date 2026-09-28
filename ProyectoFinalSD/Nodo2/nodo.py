import socket
import threading
import json
import os
import math
import time
import hashlib

from rich.console import Console
from rich.table import Table
from rich.progress import Progress
from rich.live import Live
from rich.panel import Panel


# =========================================================
# CONFIGURACION
# =========================================================

PUERTO_TRACKER = 6000

TAMANO_PIEZA = 512 * 1024

CARPETA_ARCHIVOS = "archivos"
CARPETA_DESCARGAS = "descargas"

console = Console()


os.makedirs(
    CARPETA_ARCHIVOS,
    exist_ok=True
)

os.makedirs(
    CARPETA_DESCARGAS,
    exist_ok=True
)


archivos_compartidos = []

progreso_archivos = {}

total_fragmentos = {}

transferencias_activas = {}

hashes_archivos = {}


# =========================================================
# VARIABLES QUE SE DEFINEN AL INICIAR
# =========================================================

IP_TRACKER = ""

MI_PUERTO = 0


# =========================================================
# INTEGRIDAD SHA-256
# =========================================================

def calcular_sha256(ruta):

    sha256 = hashlib.sha256()

    with open(ruta, "rb") as f:

        while True:

            bloque = f.read(1024 * 1024)

            if not bloque:
                break

            sha256.update(bloque)

    return sha256.hexdigest()


# =========================================================
# COMUNICACION CON TRACKER
# =========================================================

def enviar_tracker(mensaje):

    try:

        s = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        s.settimeout(5)

        s.connect(
            (IP_TRACKER, PUERTO_TRACKER)
        )

        s.sendall(
            json.dumps(mensaje).encode()
        )

        respuesta = b""

        try:

            respuesta = s.recv(16384)

        except socket.timeout:

            pass

        s.close()


        if respuesta:

            return json.loads(
                respuesta.decode()
            )


    except Exception as error:

        console.print(
            f"[red]No se pudo comunicar con el tracker: {error}[/red]"
        )

    return None


# =========================================================
# REGISTRARSE CON TRACKER
# =========================================================

def anunciar_tracker():

    mensaje = {

        "tipo": "REGISTRO",

        "puerto": MI_PUERTO,

        "archivos": archivos_compartidos,

        "progreso": progreso_archivos,

        "total_fragmentos": total_fragmentos,

        "hashes": hashes_archivos
    }


    enviar_tracker(mensaje)


# =========================================================
# HEARTBEAT
# =========================================================

def heartbeat():

    while True:

        anunciar_tracker()

        time.sleep(5)


# =========================================================
# SERVIDOR DEL NODO
# =========================================================

def atender_peer(conn, addr):

    try:

        datos = conn.recv(4096)

        if not datos:
            return


        mensaje = json.loads(
            datos.decode()
        )


        if mensaje["tipo"] == "PEDIR_PIEZA":

            archivo = mensaje["archivo"]

            pieza = mensaje["pieza"]


            ruta_original = os.path.join(
                CARPETA_ARCHIVOS,
                archivo
            )


            ruta_descarga = os.path.join(
                CARPETA_DESCARGAS,
                archivo
            )


            if os.path.exists(ruta_original):

                ruta = ruta_original

            elif os.path.exists(ruta_descarga):

                ruta = ruta_descarga

            else:

                return


            with open(ruta, "rb") as f:

                f.seek(
                    pieza * TAMANO_PIEZA
                )

                datos_pieza = f.read(
                    TAMANO_PIEZA
                )


            tamano = len(datos_pieza)


            conn.sendall(
                tamano.to_bytes(
                    8,
                    byteorder="big"
                )
            )


            conn.sendall(
                datos_pieza
            )


    except Exception as error:

        console.print(
            f"[red]Error enviando pieza: {error}[/red]"
        )


    finally:

        conn.close()


# =========================================================
# SERVIDOR PARA COMPARTIR ARCHIVOS
# =========================================================

def servidor_archivos():

    servidor = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )


    servidor.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_REUSEADDR,
        1
    )


    servidor.bind(
        ("0.0.0.0", MI_PUERTO)
    )


    servidor.listen(20)


    console.print(
        f"[green]Servidor del nodo activo en puerto {MI_PUERTO}[/green]"
    )


    while True:

        conn, addr = servidor.accept()


        threading.Thread(
            target=atender_peer,
            args=(conn, addr),
            daemon=True
        ).start()


# =========================================================
# OPCION 1
# VER NODOS
# =========================================================

def ver_nodos():

    respuesta = enviar_tracker({

        "tipo": "LISTAR_NODOS"

    })


    if not respuesta:

        console.print(
            "[yellow]No hay nodos conectados.[/yellow]"
        )

        return


    tabla = Table(
        title="NODOS CONECTADOS"
    )

    tabla.add_column("Nodo")
    tabla.add_column("IP")
    tabla.add_column("Puerto")
    tabla.add_column("Rol")
    tabla.add_column("Archivos")


    for nodo in respuesta:

        tabla.add_row(

            nodo["id"],

            nodo["ip"],

            str(nodo["puerto"]),

            nodo["rol"],

            ", ".join(
                nodo["archivos"]
            ) or "Ninguno"

        )


    console.print(tabla)

    console.print(
        f"\nTotal de nodos: {len(respuesta)}"
    )


# =========================================================
# VER ARCHIVOS DISPONIBLES
# =========================================================

def obtener_archivos():

    respuesta = enviar_tracker({

        "tipo": "LISTAR_ARCHIVOS"

    })

    return respuesta or []


def ver_archivos():

    archivos = obtener_archivos()


    if not archivos:

        console.print(
            "[yellow]No existen archivos disponibles.[/yellow]"
        )

        return


    tabla = Table(
        title="ARCHIVOS DISPONIBLES"
    )

    tabla.add_column("#")
    tabla.add_column("Archivo")


    for i, archivo in enumerate(
        archivos,
        start=1
    ):

        tabla.add_row(
            str(i),
            archivo
        )


    console.print(tabla)


# =========================================================
# DESCARGAR PIEZA
# =========================================================

def recibir_pieza(
    fuente,
    archivo,
    numero_pieza
):

    s = socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    )


    s.settimeout(10)


    s.connect(
        (
            fuente["ip"],
            fuente["puerto"]
        )
    )


    mensaje = {

        "tipo": "PEDIR_PIEZA",

        "archivo": archivo,

        "pieza": numero_pieza
    }


    s.sendall(
        json.dumps(mensaje).encode()
    )


    encabezado = b""


    while len(encabezado) < 8:

        datos = s.recv(
            8 - len(encabezado)
        )

        if not datos:

            raise Exception(
                "Conexión cerrada"
            )

        encabezado += datos


    tamano = int.from_bytes(
        encabezado,
        byteorder="big"
    )


    contenido = b""


    while len(contenido) < tamano:

        datos = s.recv(
            min(
                65536,
                tamano - len(contenido)
            )
        )


        if not datos:

            break


        contenido += datos


    s.close()


    return contenido


# =========================================================
# DESCARGAR ARCHIVO
# =========================================================

def descargar_archivo(
    archivo,
    fuentes
):

    if not fuentes:

        return


    total = max(

        fuente["total_fragmentos"]

        for fuente in fuentes

    )


    if total == 0:

        console.print(
            "[red]No se conoce el tamaño del archivo.[/red]"
        )

        return


    ruta = os.path.join(
        CARPETA_DESCARGAS,
        archivo
    )


    # -----------------------------------------------------
    # RECUPERACION
    # -----------------------------------------------------

    if os.path.exists(ruta):

        tamano_actual = os.path.getsize(
            ruta
        )

        pieza_inicial = (
            tamano_actual
            // TAMANO_PIEZA
        )

    else:

        pieza_inicial = 0


    progreso_archivos[archivo] = int(

        pieza_inicial
        / total
        * 100

    )


    transferencias_activas[archivo] = {

        "estado": "DESCARGANDO",

        "progreso":
            progreso_archivos[archivo]

    }


    if pieza_inicial > 0:

        console.print(

            f"[yellow]"
            f"Reanudando {archivo} "
            f"desde {progreso_archivos[archivo]}%"
            f"[/yellow]"

        )


    modo = (
        "ab"
        if pieza_inicial > 0
        else "wb"
    )


    with open(ruta, modo) as f:

        for pieza in range(
            pieza_inicial,
            total
        ):


            descargada = False


            # Intentar con diferentes fuentes
            for intento in range(
                len(fuentes)
            ):


                indice = (
                    pieza + intento
                ) % len(fuentes)


                fuente = fuentes[indice]


                try:

                    datos = recibir_pieza(
                        fuente,
                        archivo,
                        pieza
                    )


                    if datos:

                        f.write(datos)

                        f.flush()

                        descargada = True

                        break


                except Exception:

                    continue


            if not descargada:

                console.print(

                    f"[red]"
                    f"No fue posible descargar "
                    f"la pieza {pieza}."
                    f"[/red]"

                )


                transferencias_activas[
                    archivo
                ]["estado"] = "INTERRUMPIDA"


                anunciar_tracker()

                return


            porcentaje = int(

                (
                    (pieza + 1)
                    / total
                )
                * 100

            )


            progreso_archivos[
                archivo
            ] = porcentaje


            transferencias_activas[
                archivo
            ]["progreso"] = porcentaje


            # Regla del 20 %
            if porcentaje >= 20:

                if archivo not in archivos_compartidos:

                    archivos_compartidos.append(
                        archivo
                    )


                total_fragmentos[
                    archivo
                ] = total


            anunciar_tracker()


    progreso_archivos[
        archivo
    ] = 100


    transferencias_activas[
        archivo
    ]["estado"] = "COMPLETADO"


    if archivo not in archivos_compartidos:

        archivos_compartidos.append(
            archivo
        )


    total_fragmentos[
        archivo
    ] = total


    anunciar_tracker()


    hash_esperado = next(
        (fuente.get("hash") for fuente in fuentes if fuente.get("hash")),
        None
    )

    hash_descargado = calcular_sha256(ruta)

    if hash_esperado and hash_descargado == hash_esperado:

        hashes_archivos[archivo] = hash_descargado

        console.print(
            f"\n[bold green]Archivo {archivo} descargado correctamente.[/bold green]"
        )
        console.print("[bold green]INTEGRIDAD VERIFICADA ✓[/bold green]")
        console.print(f"SHA-256: {hash_descargado}")

    elif hash_esperado:

        transferencias_activas[archivo]["estado"] = "ERROR DE INTEGRIDAD"

        console.print(
            f"\n[bold red]El archivo {archivo} terminó de descargarse, "
            "pero NO coincide con el original.[/bold red]"
        )
        console.print("[bold red]ERROR DE INTEGRIDAD ✗[/bold red]")
        console.print(f"Esperado:   {hash_esperado}")
        console.print(f"Descargado: {hash_descargado}")

    else:

        console.print(
            f"\n[yellow]Archivo {archivo} descargado, pero no se recibió "
            "un SHA-256 de referencia.[/yellow]"
        )

    anunciar_tracker()


# =========================================================
# OPCION 2
# TRANSFERIR ARCHIVO
# =========================================================

def transferir_archivo():

    archivos = obtener_archivos()


    if not archivos:

        console.print(
            "[yellow]No hay archivos disponibles.[/yellow]"
        )

        return


    tabla = Table(
        title="SELECCIONAR ARCHIVO"
    )

    tabla.add_column("#")
    tabla.add_column("Archivo")


    for i, archivo in enumerate(
        archivos,
        start=1
    ):

        tabla.add_row(
            str(i),
            archivo
        )


    console.print(tabla)


    try:

        opcion = int(
            input(
                "\nSeleccione archivo: "
            )
        )


        archivo = archivos[
            opcion - 1
        ]


    except:

        console.print(
            "[red]Opción inválida.[/red]"
        )

        return


    fuentes = enviar_tracker({

        "tipo": "BUSCAR_ARCHIVO",

        "archivo": archivo

    })


    if not fuentes:

        console.print(
            "[red]No se encontraron fuentes.[/red]"
        )

        return


    console.print(

        f"\n[green]"
        f"Fuentes encontradas: "
        f"{len(fuentes)}"
        f"[/green]"

    )


    # Descargar en segundo plano
    threading.Thread(

        target=descargar_archivo,

        args=(
            archivo,
            fuentes
        ),

        daemon=True

    ).start()


    console.print(

        f"[cyan]"
        f"Transferencia de {archivo} iniciada."
        f"[/cyan]"

    )


# =========================================================
# OPCION 3
# VER PROGRESO
# =========================================================

def construir_tabla_progreso():

    tabla = Table(
        title="PROGRESO DE TRANSFERENCIAS"
    )

    tabla.add_column("Archivo")
    tabla.add_column("Progreso")
    tabla.add_column("Estado")

    for archivo, info in list(transferencias_activas.items()):

        porcentaje = info.get("progreso", 0)

        bloques = int(porcentaje / 5)

        barra = (
            "█" * bloques
            + "░" * (20 - bloques)
        )

        tabla.add_row(
            archivo,
            f"{barra} {porcentaje}%",
            info.get("estado", "DESCONOCIDO")
        )

    return tabla


def ver_progreso():

    if not transferencias_activas:

        console.print(
            "[yellow]No existen transferencias activas.[/yellow]"
        )

        return

    detener = threading.Event()

    def esperar_enter():
        input()
        detener.set()

    console.print(
        "[cyan]Progreso en vivo. Presiona ENTER para regresar al menú.[/cyan]"
    )

    threading.Thread(
        target=esperar_enter,
        daemon=True
    ).start()

    with Live(
        construir_tabla_progreso(),
        console=console,
        refresh_per_second=4
    ) as live:

        while not detener.is_set():

            live.update(
                construir_tabla_progreso()
            )

            time.sleep(0.25)


# =========================================================
# OPCION 5
# COMPARTIR ARCHIVO
# =========================================================

def compartir_archivo():

    archivos = os.listdir(
        CARPETA_ARCHIVOS
    )


    if not archivos:

        console.print(

            "[yellow]"
            "La carpeta /archivos está vacía."
            "[/yellow]"

        )

        return


    tabla = Table(
        title="MIS ARCHIVOS"
    )

    tabla.add_column("#")
    tabla.add_column("Archivo")
    tabla.add_column("Tamaño")


    for i, archivo in enumerate(
        archivos,
        start=1
    ):

        ruta = os.path.join(
            CARPETA_ARCHIVOS,
            archivo
        )


        tamano_mb = (
            os.path.getsize(ruta)
            / 1024
            / 1024
        )


        tabla.add_row(

            str(i),

            archivo,

            f"{tamano_mb:.2f} MB"

        )


    console.print(tabla)


    try:

        opcion = int(
            input(
                "\nSeleccione archivo: "
            )
        )


        archivo = archivos[
            opcion - 1
        ]


    except:

        console.print(
            "[red]Opción inválida.[/red]"
        )

        return


    ruta = os.path.join(
        CARPETA_ARCHIVOS,
        archivo
    )


    tamano = os.path.getsize(
        ruta
    )


    fragmentos = math.ceil(

        tamano
        / TAMANO_PIEZA

    )


    console.print("[cyan]Calculando SHA-256 del archivo...[/cyan]")

    hash_archivo = calcular_sha256(ruta)

    hashes_archivos[archivo] = hash_archivo

    if archivo not in archivos_compartidos:
        archivos_compartidos.append(archivo)


    progreso_archivos[
        archivo
    ] = 100


    total_fragmentos[
        archivo
    ] = fragmentos


    anunciar_tracker()


    console.print(

        f"\n[bold green]"
        f"Compartiendo {archivo}"
        f"[/bold green]"

    )


    console.print(
        f"Tamaño: {tamano / 1024 / 1024:.2f} MB"
    )

    console.print(
        f"Fragmentos: {fragmentos}"
    )

    console.print(
        f"SHA-256: {hash_archivo}"
    )


# =========================================================
# MENU PRINCIPAL
# =========================================================

def menu():

    while True:

        console.print(
            "\n[bold cyan]"
            "=========================================="
            "[/bold cyan]"
        )

        console.print(
            "[bold cyan]"
            "       RED DISTRIBUIDA BITTORRENT"
            "[/bold cyan]"
        )

        console.print(
            "[bold cyan]"
            "=========================================="
            "[/bold cyan]"
        )


        print(
            f"\nTracker: {IP_TRACKER}:{PUERTO_TRACKER}"
        )

        print(
            f"Puerto del nodo: {MI_PUERTO}\n"
        )


        print("1. Ver nodos conectados")

        print("2. Transferir archivo")

        print("3. Ver progreso")

        print("4. Ver archivos disponibles")

        print("5. Compartir archivo")

        print("6. Salir")


        opcion = input(
            "\nSeleccione una opción: "
        )


        if opcion == "1":

            ver_nodos()


        elif opcion == "2":

            transferir_archivo()


        elif opcion == "3":

            ver_progreso()


        elif opcion == "4":

            ver_archivos()


        elif opcion == "5":

            compartir_archivo()


        elif opcion == "6":

            print(
                "Cerrando nodo..."
            )

            os._exit(0)


        else:

            console.print(
                "[red]Opción inválida.[/red]"
            )


# =========================================================
# INICIO
# =========================================================

if __name__ == "__main__":

    console.print(
        "\n[bold cyan]"
        "INICIANDO NODO BITTORRENT"
        "[/bold cyan]\n"
    )


    IP_TRACKER = input(
        "IP del Tracker: "
    )


    MI_PUERTO = int(
        input(
            "Puerto de este nodo: "
        )
    )


    # Servidor para recibir peticiones
    threading.Thread(

        target=servidor_archivos,

        daemon=True

    ).start()


    # Heartbeat
    threading.Thread(

        target=heartbeat,

        daemon=True

    ).start()


    time.sleep(1)


    menu()