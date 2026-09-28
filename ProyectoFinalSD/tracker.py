import socket
import threading
import json
import time

from rich.console import Console
from rich.table import Table


PUERTO_TRACKER = 6000
TIEMPO_LIMITE = 15

console = Console()

nodos = {}
lock = threading.Lock()


# =========================================================
# LIMPIAR NODOS DESCONECTADOS
# =========================================================

def limpiar_nodos():

    while True:

        time.sleep(5)

        ahora = time.time()

        with lock:

            desconectados = []

            for nodo_id, info in nodos.items():

                if ahora - info["ultima_vez"] > TIEMPO_LIMITE:

                    desconectados.append(nodo_id)

            for nodo_id in desconectados:

                del nodos[nodo_id]

                console.print(
                    f"[red]Nodo desconectado: {nodo_id}[/red]"
                )


# =========================================================
# MOSTRAR ESTADO DE LA RED
# =========================================================

def mostrar_estado():

    tabla = Table(
        title="ESTADO DE LA RED BITTORRENT"
    )

    tabla.add_column("Nodo")
    tabla.add_column("IP")
    tabla.add_column("Puerto")
    tabla.add_column("Rol")
    tabla.add_column("Archivos")
    tabla.add_column("Progreso")


    with lock:

        for nodo_id, info in nodos.items():

            progreso = info.get("progreso", {})

            # Determinar rol
            if any(p == 100 for p in progreso.values()):

                rol = "SEEDER"

            elif any(0 < p < 100 for p in progreso.values()):

                rol = "LEECHER"

            else:

                rol = "PEER"


            archivos = ", ".join(
                info.get("archivos", [])
            )

            progreso_txt = ", ".join(
                f"{archivo}: {porcentaje}%"
                for archivo, porcentaje in progreso.items()
            )


            tabla.add_row(

                nodo_id,
                info["ip"],
                str(info["puerto"]),
                rol,
                archivos if archivos else "Ninguno",
                progreso_txt if progreso_txt else "Sin transferencias"

            )


    console.print(tabla)


# =========================================================
# MANEJAR PETICIONES DE LOS NODOS
# =========================================================

def manejar_cliente(conn, addr):

    try:

        datos = conn.recv(8192)

        if not datos:
            return

        mensaje = json.loads(
            datos.decode("utf-8")
        )

        tipo = mensaje.get("tipo")


        # -------------------------------------------------
        # REGISTRO / HEARTBEAT
        # -------------------------------------------------

        if tipo == "REGISTRO":

            ip = addr[0]

            puerto = mensaje["puerto"]

            nodo_id = f"{ip}:{puerto}"


            with lock:

                nodos[nodo_id] = {

                    "ip": ip,

                    "puerto": puerto,

                    "archivos": mensaje.get(
                        "archivos", []
                    ),

                    "progreso": mensaje.get(
                        "progreso", {}
                    ),

                    "total_fragmentos": mensaje.get(
                        "total_fragmentos", {}
                    ),

                    "ultima_vez": time.time()
                }


            console.print(
                f"[green]Nodo activo: {nodo_id}[/green]"
            )


        # -------------------------------------------------
        # LISTAR NODOS
        # -------------------------------------------------

        elif tipo == "LISTAR_NODOS":

            respuesta = []

            with lock:

                for nodo_id, info in nodos.items():

                    progreso = info.get(
                        "progreso", {}
                    )

                    if any(
                        p == 100
                        for p in progreso.values()
                    ):

                        rol = "SEEDER"

                    elif any(
                        0 < p < 100
                        for p in progreso.values()
                    ):

                        rol = "LEECHER"

                    else:

                        rol = "PEER"


                    respuesta.append({

                        "id": nodo_id,

                        "ip": info["ip"],

                        "puerto": info["puerto"],

                        "rol": rol,

                        "archivos": info["archivos"]

                    })


            conn.sendall(
                json.dumps(respuesta).encode()
            )


        # -------------------------------------------------
        # LISTAR ARCHIVOS
        # -------------------------------------------------

        elif tipo == "LISTAR_ARCHIVOS":

            archivos = set()

            with lock:

                for info in nodos.values():

                    for archivo in info["archivos"]:

                        archivos.add(archivo)


            conn.sendall(

                json.dumps(
                    sorted(list(archivos))
                ).encode()

            )


        # -------------------------------------------------
        # BUSCAR NODOS QUE TIENEN UN ARCHIVO
        # -------------------------------------------------

        elif tipo == "BUSCAR_ARCHIVO":

            archivo = mensaje["archivo"]

            fuentes = []


            with lock:

                for info in nodos.values():

                    progreso = info.get(
                        "progreso", {}
                    )

                    porcentaje = progreso.get(
                        archivo, 0
                    )


                    # Política del proyecto:
                    # compartir desde 20 %
                    if porcentaje >= 20:

                        fuentes.append({

                            "ip": info["ip"],

                            "puerto": info["puerto"],

                            "total_fragmentos":
                                info["total_fragmentos"].get(
                                    archivo, 0
                                )

                        })


            conn.sendall(
                json.dumps(fuentes).encode()
            )


        # -------------------------------------------------
        # ESTADO DEL TRACKER
        # -------------------------------------------------

        elif tipo == "MOSTRAR_ESTADO":

            mostrar_estado()


    except Exception as error:

        console.print(
            f"[red]Error: {error}[/red]"
        )


    finally:

        conn.close()


# =========================================================
# INICIAR TRACKER
# =========================================================

def iniciar_tracker():

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
        ("0.0.0.0", PUERTO_TRACKER)
    )

    servidor.listen(20)


    console.print(
        "\n[bold green]"
        "TRACKER INICIADO"
        "[/bold green]"
    )

    console.print(
        f"Puerto: {PUERTO_TRACKER}"
    )

    console.print(
        "Esperando nodos...\n"
    )


    # Thread encargado de detectar nodos muertos
    threading.Thread(
        target=limpiar_nodos,
        daemon=True
    ).start()


    while True:

        conn, addr = servidor.accept()

        threading.Thread(
            target=manejar_cliente,
            args=(conn, addr),
            daemon=True
        ).start()


if __name__ == "__main__":

    iniciar_tracker()