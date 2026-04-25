extends Node2D

@export var target_fps: int = 60
@export var background_music: MusicTrack


func _ready() -> void:
	Engine.max_fps = target_fps
	DisplayServer.window_set_title("Tabzer Game")

	if background_music != null:
		MusicDirector.play_track(background_music)
