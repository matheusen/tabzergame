extends Node2D

@export var hero_path: NodePath = NodePath("Hero")
@export var wall_guitar_path: NodePath = NodePath("World/OfficeProps/WallGuitar")
@export var ai_disk_path: NodePath = NodePath("World/OfficeProps/AIDisk")
@export var prompt_path: NodePath = NodePath("UI/Prompt")
@export var objective_path: NodePath = NodePath("UI/Objective")
@export var agent_paths: Array[NodePath] = [
	NodePath("AgentIntruderA"),
	NodePath("AgentIntruderB"),
	NodePath("AgentIntruderShooter"),
]
@export var guitar_pickup_distance: float = 120.0

@onready var hero: CharacterBody2D = get_node(hero_path) as CharacterBody2D
@onready var wall_guitar: Node2D = get_node(wall_guitar_path) as Node2D
@onready var ai_disk: Node2D = get_node(ai_disk_path) as Node2D
@onready var prompt: Label = get_node(prompt_path) as Label
@onready var objective: Label = get_node(objective_path) as Label

var agents: Array[CharacterBody2D] = []
var guitar_taken := false
var intro_started := false


func _ready() -> void:
	for path in agent_paths:
		var agent := get_node_or_null(path) as CharacterBody2D
		if agent == null:
			continue
		agents.append(agent)
		agent.set_physics_process(false)

	prompt.visible = false
	objective.text = "Cena 1: proteja o disco da IA avancada."
	_start_intro()


func _process(_delta: float) -> void:
	if guitar_taken:
		return

	var close_to_guitar := hero.global_position.distance_to(wall_guitar.global_position) <= guitar_pickup_distance
	prompt.visible = close_to_guitar
	if close_to_guitar:
		prompt.text = "Pressione E para pegar a guitarra"
		if Input.is_key_pressed(KEY_E) or Input.is_key_pressed(KEY_F):
			_take_guitar()


func _start_intro() -> void:
	if intro_started:
		return

	intro_started = true
	objective.text = "Os agentes invadiram o escritorio. Eles querem o disco da IA."
	await get_tree().create_timer(0.8).timeout
	_move_agents_into_room()
	await get_tree().create_timer(1.0).timeout
	objective.text = "Olhe para a parede e pegue a guitarra para se defender."


func _move_agents_into_room() -> void:
	var targets := [Vector2(1220, 515), Vector2(1450, 515), Vector2(1700, 405)]
	for index in agents.size():
		var agent := agents[index]
		var target := targets[index] if index < targets.size() else Vector2(1280 + index * 160, 515)
		var tween := create_tween()
		tween.tween_property(agent, "global_position", target, 1.4).set_trans(Tween.TRANS_SINE).set_ease(Tween.EASE_OUT)
		tween.finished.connect(_enable_agent_after_intro.bind(agent))


func _enable_agent_after_intro(agent: CharacterBody2D) -> void:
	if is_instance_valid(agent):
		agent.velocity = Vector2.ZERO
		agent.set("patrol_origin", agent.global_position)
		agent.set_physics_process(true)


func _take_guitar() -> void:
	guitar_taken = true
	prompt.visible = false
	wall_guitar.visible = false
	if hero.has_method("equip_wall_guitar"):
		hero.equip_wall_guitar()
	objective.text = "Guitarra equipada. Defenda o disco da IA avancada."
	_flash_disk()


func _flash_disk() -> void:
	var tween := create_tween()
	tween.set_loops(4)
	tween.tween_property(ai_disk, "modulate", Color(0.25, 0.85, 1.0, 1.0), 0.12)
	tween.tween_property(ai_disk, "modulate", Color.WHITE, 0.18)
