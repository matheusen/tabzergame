extends CharacterBody2D

@export var run_speed: float = 360.0
@export var crouch_speed: float = 120.0
@export var jump_velocity: float = -620.0
@export var gravity_multiplier: float = 1.65
@export var normal_collision_size := Vector2(92.0, 190.0)
@export var crouch_collision_size := Vector2(92.0, 112.0)
@export var normal_collision_position := Vector2(0.0, -95.0)
@export var crouch_collision_position := Vector2(0.0, -56.0)

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D

var jump_requested := false
var requested_attack: StringName = &""
var is_crouching := false
var rectangle_shape: RectangleShape2D


func _ready() -> void:
	rectangle_shape = collision_shape.shape.duplicate() as RectangleShape2D
	collision_shape.shape = rectangle_shape
	_apply_crouch(false)
	sprite.sprite_frames = _create_sprite_frames()
	sprite.play("idle")


func _unhandled_input(event: InputEvent) -> void:
	if event is InputEventKey and event.pressed and not event.echo:
		if event.keycode in [KEY_SPACE, KEY_W, KEY_UP]:
			jump_requested = true
		elif event.keycode in [KEY_J, KEY_CTRL]:
			requested_attack = &"attack_light"
		elif event.keycode == KEY_K:
			requested_attack = &"attack_heavy"


func _physics_process(delta: float) -> void:
	var direction := _read_direction()
	var gravity := float(ProjectSettings.get_setting("physics/2d/default_gravity"))
	var wants_crouch := _read_crouch() and is_on_floor()

	_apply_crouch(wants_crouch)
	velocity.x = direction * (crouch_speed if is_crouching else run_speed)

	if not is_on_floor():
		velocity.y += gravity * gravity_multiplier * delta
	elif jump_requested and not is_crouching:
		velocity.y = jump_velocity

	jump_requested = false
	move_and_slide()

	if direction != 0.0:
		sprite.flip_h = direction < 0.0

	_update_animation(direction)


func _read_direction() -> float:
	var left := Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT)
	var right := Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT)

	if left == right:
		return 0.0

	return -1.0 if left else 1.0


func _read_crouch() -> bool:
	return Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN)


func _apply_crouch(enabled: bool) -> void:
	if is_crouching == enabled:
		return

	is_crouching = enabled
	rectangle_shape.size = crouch_collision_size if enabled else normal_collision_size
	collision_shape.position = crouch_collision_position if enabled else normal_collision_position

	if enabled:
		sprite.play("crouch_down")
	else:
		sprite.play("idle")


func _update_animation(direction: float) -> void:
	if requested_attack != &"" and not is_crouching:
		sprite.play(requested_attack)
		requested_attack = &""
		return

	if sprite.animation.begins_with("attack") and sprite.is_playing():
		return

	if is_crouching:
		if sprite.animation == "crouch_down" and sprite.is_playing():
			return

		_play_if_needed("crouch")
	elif not is_on_floor():
		_play_if_needed("jump")
	elif direction != 0.0:
		_play_if_needed("run")
	else:
		_play_if_needed("idle")


func _play_if_needed(animation_name: StringName) -> void:
	if sprite.animation != animation_name:
		sprite.play(animation_name)


func _create_sprite_frames() -> SpriteFrames:
	var frames := SpriteFrames.new()
	_add_animation(frames, "idle", 1.0, true, 1)
	_add_animation(frames, "run", 12.0, true, 6)
	_add_animation(frames, "jump", 8.0, false, 3)
	_add_animation(frames, "crouch_down", 10.0, false, 4)
	_add_animation(frames, "crouch", 1.0, true, 1)
	_add_animation(frames, "attack_light", 12.0, false, 5)
	_add_animation(frames, "attack_heavy", 10.0, false, 6)
	return frames


func _add_animation(frames: SpriteFrames, animation_name: StringName, speed: float, loops: bool, count: int) -> void:
	frames.add_animation(animation_name)
	frames.set_animation_speed(animation_name, speed)
	frames.set_animation_loop(animation_name, loops)

	for index in count:
		var path := "res://art/Player/Generated/%s_%02d.png" % [animation_name, index]
		frames.add_frame(animation_name, load(path))
