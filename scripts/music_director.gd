extends Node

var player: AudioStreamPlayer
var current_track: MusicTrack


func _ready() -> void:
	player = AudioStreamPlayer.new()
	player.name = "MusicPlayer"
	player.bus = "Music"
	add_child(player)
	player.finished.connect(_on_track_finished)


func play_track(track: MusicTrack) -> void:
	if track == null or track.stream == null:
		return

	if DisplayServer.get_name() == "headless":
		return

	if current_track == track and player.playing:
		return

	current_track = track
	player.stream = track.stream
	player.volume_db = track.volume_db
	player.play()


func stop_music() -> void:
	current_track = null
	player.stop()
	player.stream = null


func _on_track_finished() -> void:
	if current_track != null and current_track.loop:
		player.play()


func _exit_tree() -> void:
	if player != null:
		player.stop()
		player.stream = null
	current_track = null
