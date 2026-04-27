extends Resource
class_name MusicTrack

@export var track_name: StringName
@export var stream: AudioStream
@export_range(-40.0, 6.0, 0.1) var volume_db: float = -8.0
@export var loop: bool = true
