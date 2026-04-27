extends CharacterBody2D

@export var run_speed: float = 360.0
@export var crouch_speed: float = 120.0
@export var jump_velocity: float = -620.0
@export var gravity_multiplier: float = 1.65
@export var normal_collision_size := Vector2(92.0, 190.0)
@export var crouch_collision_size := Vector2(92.0, 112.0)
@export var normal_collision_position := Vector2(0.0, -95.0)
@export var crouch_collision_position := Vector2(0.0, -56.0)
@export var max_health: int = 100
@export var light_attack_damage: int = 20
@export var heavy_attack_damage: int = 35
@export var light_attack_active_time: float = 0.16
@export var heavy_attack_active_time: float = 0.24
@export var hitstun_duration: float = 0.18
@export var damage_flash_duration: float = 0.08
@export var knockback_decay: float = 2400.0
@export var guard_damage_taken_ratio: float = 0.15
@export var perfect_parry_window: float = 0.18
@export var guard_impact_duration: float = 0.18
@export var guard_recover_time: float = 0.12
@export var block_knockback: float = 140.0

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D
@onready var collision_shape: CollisionShape2D = $CollisionShape2D
@onready var attack_hitbox: Area2D = get_node_or_null("AttackHitbox") as Area2D

var jump_requested := false
var requested_attack: StringName = &""
var is_crouching := false
var is_guarding := false
var guard_was_pressed := false
var rectangle_shape: RectangleShape2D
var health: int
var attack_damage := 0
var attack_targets_hit: Array[Node] = []
var hitstun_timer := 0.0
var parry_timer := 0.0
var guard_impact_timer := 0.0
var guard_recover_timer := 0.0
var has_wall_guitar := false


func _ready() -> void:
	add_to_group("player")
	health = max_health
	rectangle_shape = collision_shape.shape.duplicate() as RectangleShape2D
	collision_shape.shape = rectangle_shape
	if attack_hitbox != null:
		attack_hitbox.monitoring = false
		attack_hitbox.area_entered.connect(_on_attack_hitbox_area_entered)
		attack_hitbox.body_entered.connect(_on_attack_hitbox_body_entered)
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
	hitstun_timer = max(hitstun_timer - delta, 0.0)
	parry_timer = max(parry_timer - delta, 0.0)
	guard_impact_timer = max(guard_impact_timer - delta, 0.0)
	guard_recover_timer = max(guard_recover_timer - delta, 0.0)
	var direction := _read_direction()
	var gravity := float(ProjectSettings.get_setting("physics/2d/default_gravity"))
	var wants_guard := _read_guard() and is_on_floor() and hitstun_timer <= 0.0
	var wants_crouch := _read_crouch() and is_on_floor()

	_apply_crouch(wants_crouch)
	_update_guard(wants_guard, delta)
	if hitstun_timer <= 0.0 and not is_guarding:
		velocity.x = direction * (crouch_speed if is_crouching else run_speed)
	elif is_guarding:
		velocity.x = 0.0
	else:
		velocity.x = move_toward(velocity.x, 0.0, knockback_decay * delta)

	if not is_on_floor():
		velocity.y += gravity * gravity_multiplier * delta
	elif jump_requested and not is_crouching and not is_guarding and hitstun_timer <= 0.0:
		velocity.y = jump_velocity

	jump_requested = false
	move_and_slide()

	if direction != 0.0:
		sprite.flip_h = direction < 0.0
		_update_attack_hitbox_direction()

	_update_animation(direction)


func _read_direction() -> float:
	var left := Input.is_key_pressed(KEY_A) or Input.is_key_pressed(KEY_LEFT)
	var right := Input.is_key_pressed(KEY_D) or Input.is_key_pressed(KEY_RIGHT)

	if left == right:
		return 0.0

	return -1.0 if left else 1.0


func _read_crouch() -> bool:
	return Input.is_key_pressed(KEY_S) or Input.is_key_pressed(KEY_DOWN)


func _read_guard() -> bool:
	return Input.is_key_pressed(KEY_Q) or Input.is_key_pressed(KEY_L) or Input.is_mouse_button_pressed(MOUSE_BUTTON_RIGHT)


func equip_wall_guitar() -> void:
	has_wall_guitar = true
	light_attack_damage = maxi(light_attack_damage, 24)
	heavy_attack_damage = maxi(heavy_attack_damage, 42)
	guard_damage_taken_ratio = minf(guard_damage_taken_ratio, 0.08)


func _update_guard(wants_guard: bool, _delta: float) -> void:
	var can_guard := wants_guard and not _is_attack_locked()
	is_guarding = can_guard
	if is_guarding:
		requested_attack = &""
		if attack_hitbox != null:
			attack_hitbox.monitoring = false

	if is_guarding and not guard_was_pressed:
		parry_timer = perfect_parry_window
		guard_recover_timer = 0.0
		guard_impact_timer = 0.0
		sprite.play("crouch_guard" if is_crouching else "guard_raise")
	elif not is_guarding and guard_was_pressed and hitstun_timer <= 0.0:
		guard_recover_timer = guard_recover_time
		if not is_crouching:
			sprite.play("guard_recover")

	guard_was_pressed = is_guarding


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
	if guard_impact_timer > 0.0 and _is_guard_animation(sprite.animation):
		return

	if guard_recover_timer > 0.0 and sprite.animation == &"guard_recover":
		return

	if is_guarding:
		if is_crouching:
			_play_if_needed(&"crouch_guard")
		elif sprite.animation == &"guard_raise" and sprite.is_playing():
			return
		else:
			_play_if_needed(&"guard_hold")
		return

	if requested_attack != &"" and not is_crouching and hitstun_timer <= 0.0:
		sprite.play(requested_attack)
		_start_attack(requested_attack)
		requested_attack = &""
		return

	if sprite.animation.begins_with("attack") and sprite.is_playing():
		return

	if is_crouching:
		if sprite.animation == "crouch_down" and sprite.is_playing():
			return

		_play_if_needed("crouch_move" if direction != 0.0 else "crouch")
	elif not is_on_floor():
		_play_if_needed("jump")
	elif direction != 0.0:
		_play_if_needed("run")
	else:
		_play_if_needed("idle")


func _play_if_needed(animation_name: StringName) -> void:
	if sprite.animation != animation_name:
		sprite.play(animation_name)


func _is_attack_locked() -> bool:
	return sprite.animation.begins_with("attack") and sprite.is_playing()


func _is_guard_animation(animation_name: StringName) -> bool:
	return animation_name in [
		&"guard_raise",
		&"guard_hold",
		&"guard_impact",
		&"crouch_guard",
		&"crouch_block_impact",
		&"parry",
		&"block_recoil",
		&"guard_break",
		&"guard_recover",
	]


func _create_sprite_frames() -> SpriteFrames:
	var frames := SpriteFrames.new()
	_add_animation(frames, "idle", 1.0, true, 1)
	_add_animation(frames, "run", 12.0, true, 6)
	_add_animation(frames, "jump", 8.0, false, 3)
	_add_animation(frames, "crouch_down", 10.0, false, 4)
	_add_animation(frames, "crouch", 1.0, true, 1)
	_add_animation(frames, "crouch_move", 10.0, true, 6)
	_add_animation(frames, "attack_light", 12.0, false, 5)
	_add_animation(frames, "attack_heavy", 10.0, false, 6)
	_add_defense_animation(frames, &"guard_raise", 10.0, false, [&"guard_ready_00", &"guard_raise_00", &"guard_hold_00"])
	_add_defense_animation(frames, &"guard_hold", 1.0, true, [&"guard_hold_00"])
	_add_defense_animation(frames, &"guard_impact", 12.0, false, [&"guard_hold_00", &"guard_impact_00"])
	_add_defense_animation(frames, &"crouch_guard", 1.0, true, [&"crouch_guard_00"])
	_add_defense_animation(frames, &"crouch_block_impact", 12.0, false, [&"crouch_guard_00", &"crouch_block_impact_00"])
	_add_defense_animation(frames, &"parry", 14.0, false, [&"guard_hold_00", &"parry_00"])
	_add_defense_animation(frames, &"block_recoil", 10.0, false, [&"guard_impact_00", &"block_recoil_00"])
	_add_defense_animation(frames, &"guard_break", 10.0, false, [&"guard_break_00"])
	_add_defense_animation(frames, &"guard_recover", 10.0, false, [&"guard_recover_00"])
	return frames


func _add_animation(frames: SpriteFrames, animation_name: StringName, speed: float, loops: bool, count: int) -> void:
	frames.add_animation(animation_name)
	frames.set_animation_speed(animation_name, speed)
	frames.set_animation_loop(animation_name, loops)

	for index in count:
		var path := "res://art/Player/Generated/%s_%02d.png" % [animation_name, index]
		frames.add_frame(animation_name, load(path))


func _add_defense_animation(frames: SpriteFrames, animation_name: StringName, speed: float, loops: bool, file_names: Array) -> void:
	frames.add_animation(animation_name)
	frames.set_animation_speed(animation_name, speed)
	frames.set_animation_loop(animation_name, loops)

	for file_name: StringName in file_names:
		var path := "res://art/Player/Defense/%s.png" % file_name
		frames.add_frame(animation_name, load(path))


func take_damage(amount: int) -> void:
	health = max(health - amount, 0)
	hitstun_timer = hitstun_duration
	modulate = Color(1.0, 0.55, 0.55, 1.0)
	await get_tree().create_timer(damage_flash_duration).timeout
	modulate = Color.WHITE


func apply_melee_hit(amount: int, attacker_x: float, horizontal_force: float = 380.0, vertical_force: float = -90.0) -> void:
	if _try_defend(amount, attacker_x):
		return

	take_damage(amount)
	var push_direction := 1.0 if global_position.x >= attacker_x else -1.0
	velocity.x = push_direction * horizontal_force
	if is_on_floor():
		velocity.y = vertical_force


func apply_projectile_hit(amount: int, projectile_position: Vector2) -> void:
	if _try_defend(amount, projectile_position.x):
		return

	take_damage(amount)


func can_be_hit_by_bullet(bullet_position: Vector2) -> bool:
	if not is_crouching:
		return true

	var crouch_top_y := global_position.y + crouch_collision_position.y - crouch_collision_size.y * 0.5
	return bullet_position.y >= crouch_top_y


func _try_defend(amount: int, attacker_x: float) -> bool:
	if not is_guarding or hitstun_timer > 0.0 or not is_on_floor():
		return false
	if not _is_facing_threat(attacker_x):
		return false

	if parry_timer > 0.0:
		parry_timer = 0.0
		guard_impact_timer = guard_impact_duration
		sprite.play("parry")
		velocity.x = 0.0
		return true

	var blocked_damage := int(round(float(amount) * guard_damage_taken_ratio))
	health = max(health - blocked_damage, 0)
	guard_impact_timer = guard_impact_duration
	if is_crouching:
		sprite.play("crouch_block_impact")
	elif amount >= 14:
		sprite.play("block_recoil")
	else:
		sprite.play("guard_impact")
	var push_direction := 1.0 if global_position.x >= attacker_x else -1.0
	velocity.x = push_direction * block_knockback
	if health <= 0:
		sprite.play("guard_break")
	return true


func _is_facing_threat(attacker_x: float) -> bool:
	var threat_direction: float = sign(attacker_x - global_position.x)
	if threat_direction == 0.0:
		return true

	return threat_direction < 0.0 if sprite.flip_h else threat_direction > 0.0


func _start_attack(animation_name: StringName) -> void:
	if attack_hitbox == null:
		return

	attack_damage = heavy_attack_damage if animation_name == &"attack_heavy" else light_attack_damage
	attack_targets_hit.clear()
	_update_attack_hitbox_direction()
	attack_hitbox.monitoring = true

	var active_time := heavy_attack_active_time if animation_name == &"attack_heavy" else light_attack_active_time
	await get_tree().create_timer(active_time).timeout
	if attack_hitbox != null:
		attack_hitbox.monitoring = false


func _update_attack_hitbox_direction() -> void:
	if attack_hitbox == null:
		return

	attack_hitbox.position.x = -76.0 if sprite.flip_h else 76.0


func _on_attack_hitbox_area_entered(area: Area2D) -> void:
	_try_damage_target(area)


func _on_attack_hitbox_body_entered(body: Node2D) -> void:
	_try_damage_target(body)


func _try_damage_target(target: Node) -> void:
	var damage_target := target
	if not damage_target.has_method("take_damage") and target.get_parent() != null:
		damage_target = target.get_parent()

	if damage_target in attack_targets_hit or not damage_target.has_method("take_damage"):
		return

	attack_targets_hit.append(damage_target)
	damage_target.take_damage(attack_damage)
