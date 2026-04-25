extends Camera2D

@export var target_path: NodePath
@export var follow_offset: Vector2 = Vector2(220.0, -130.0)
@export var follow_speed: float = 12.0

@onready var target := get_node_or_null(target_path) as Node2D


func _ready() -> void:
	make_current()


func _process(delta: float) -> void:
	if target == null:
		return

	var desired_position := target.global_position + follow_offset
	var weight := 1.0 - exp(-follow_speed * delta)
	global_position = global_position.lerp(desired_position, weight).round()
