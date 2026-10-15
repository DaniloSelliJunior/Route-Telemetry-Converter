"""Definição dos pacotes do datalogger ESP32 (Little-Endian).

Cada pacote no .bin tem o layout:
    1 byte  : ID do pacote
    4 bytes : timestamp local (uint32, ms)
    N bytes : payload (definido por `payload_fmt`)

Para adicionar um pacote novo, basta incluir um PacketDef em PACKETS.
O parser NÃO consegue pular pacotes de ID desconhecido (não há campo de
tamanho no stream), então todo ID presente no .bin precisa estar aqui.
"""

from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class Channel:
    name: str
    unit: str = ""
    decimals: int = 3
    hold: bool = False      # True = mantém o último valor (canais discretos, ex.: marcha)


@dataclass(frozen=True)
class PacketDef:
    packet_id: int
    name: str
    freq_hz: float          # frequência nominal do grupo (usada no .ld)
    payload_fmt: str        # formato struct do payload, SEM o "<"
    channels: tuple         # um Channel por campo do payload, na ordem

    def __post_init__(self):
        n_fields = len(struct.unpack("<" + self.payload_fmt,
                                     bytes(struct.calcsize("<" + self.payload_fmt))))
        if n_fields != len(self.channels):
            raise ValueError(
                f"Pacote 0x{self.packet_id:02X}: {n_fields} campos no formato "
                f"mas {len(self.channels)} canais definidos")

    @property
    def struct(self) -> struct.Struct:
        # "<BI" = ID + timestamp, depois o payload
        return struct.Struct("<BI" + self.payload_fmt)

    @property
    def size(self) -> int:
        return self.struct.size


PACKETS = {
    # 0x01 - Chassi & IMU - 200 Hz - 29 bytes (1 + 4 + 6*4)
    0x01: PacketDef(
        packet_id=0x01,
        name="Chassi_IMU",
        freq_hz=200.0,
        payload_fmt="6f",
        channels=(
            Channel("Acel_X", "g"),      # ajuste a unidade conforme o firmware
            Channel("Acel_Y", "g"),
            Channel("Acel_Z", "g"),
            Channel("Gyro_X", "deg/s"),
            Channel("Gyro_Y", "deg/s"),
            Channel("Gyro_Z", "deg/s"),
        ),
    ),

    # 0x02 - Pedais e Freios - 50 Hz - 21 bytes (1 + 4 + 4*4)
    0x02: PacketDef(
        packet_id=0x02,
        name="Pedais_Freios",
        freq_hz=50.0,
        payload_fmt="4f",
        channels=(
            Channel("Hall_Acelerador", "%", 1),
            Channel("Hall_Freio", "%", 1),
            Channel("Pressao_Freio_Diant", "PSI", 1),
            Channel("Pressao_Freio_Tras", "PSI", 1),
        ),
    ),

    # 0x03 - Motor Rapido (ECU) - 50 Hz - 24 bytes (1 + 4 + 2 + 1 + 4*4)
    0x03: PacketDef(
        packet_id=0x03,
        name="Motor_Rapido",
        freq_hz=50.0,
        payload_fmt="Hb4f",
        channels=(
            Channel("RPM", "rpm", 0),
            Channel("Marcha", "", 0, hold=True),
            Channel("TPS", "%", 1),
            Channel("MAP", "kPa", 1),
            Channel("Angulo_Ignicao", "deg", 1),
            Channel("Velocidade", "km/h", 1),
        ),
    ),

    # 0x04 - Motor Lento (temperaturas e fluidos) - 10 Hz - 33 bytes (1 + 4 + 7*4)
    0x04: PacketDef(
        packet_id=0x04,
        name="Motor_Lento",
        freq_hz=10.0,
        payload_fmt="7f",
        channels=(
            Channel("Temp_Motor", "C", 1),
            Channel("Temp_Ar_IAT", "C", 1),
            Channel("Pressao_Oleo", "bar", 2),
            Channel("Pressao_Combustivel", "bar", 2),
            Channel("Tensao_Bateria", "V", 2),
            Channel("Lambda_1", "", 3),
            Channel("Nivel_Combustivel", "L", 2),
        ),
    ),
}
