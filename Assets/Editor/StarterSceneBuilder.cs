using System.IO;
using TabzerGame.CameraTools;
using TabzerGame.Core;
using TabzerGame.Player;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace TabzerGame.EditorTools
{
    public static class StarterSceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/Main.unity";

        [MenuItem("Tabzer/Create Starter Scene")]
        public static void CreateStarterScene()
        {
            Directory.CreateDirectory("Assets/Scenes");
            Directory.CreateDirectory("Assets/Art/Placeholders");

            Sprite playerSprite = CreateSolidSprite("Assets/Art/Placeholders/player_placeholder.png", new Color32(241, 145, 58, 255));
            Sprite groundSprite = CreateSolidSprite("Assets/Art/Placeholders/ground_placeholder.png", new Color32(43, 38, 32, 255));

            Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            scene.name = "Main";

            GameObject gameManager = new("Game Bootstrap");
            gameManager.AddComponent<GameBootstrap>();

            GameObject player = new("Hero");
            player.transform.position = new Vector3(-4f, -1f, 0f);
            player.AddComponent<SpriteRenderer>().sprite = playerSprite;
            Rigidbody2D body = player.AddComponent<Rigidbody2D>();
            body.gravityScale = 3.2f;
            player.AddComponent<BoxCollider2D>().size = new Vector2(0.8f, 1.2f);
            player.AddComponent<HeroController2D>();

            GameObject ground = new("Ground");
            ground.transform.position = new Vector3(0f, -2.15f, 0f);
            ground.transform.localScale = new Vector3(16f, 1f, 1f);
            ground.AddComponent<SpriteRenderer>().sprite = groundSprite;
            ground.AddComponent<BoxCollider2D>();

            Camera camera = new GameObject("Main Camera").AddComponent<Camera>();
            camera.tag = "MainCamera";
            camera.orthographic = true;
            camera.orthographicSize = 5f;
            camera.transform.position = new Vector3(0f, 0f, -10f);
            camera.gameObject.AddComponent<AudioListener>();
            camera.gameObject.AddComponent<CameraFollow2D>().SetTarget(player.transform);

            EditorSceneManager.SaveScene(scene, ScenePath);
            EditorBuildSettings.scenes = new[] { new EditorBuildSettingsScene(ScenePath, true) };
            AssetDatabase.SaveAssets();
            AssetDatabase.Refresh();
        }

        private static Sprite CreateSolidSprite(string path, Color32 color)
        {
            if (!File.Exists(path))
            {
                Texture2D texture = new(16, 16, TextureFormat.RGBA32, false);
                Color32[] pixels = new Color32[16 * 16];

                for (int i = 0; i < pixels.Length; i++)
                {
                    pixels[i] = color;
                }

                texture.SetPixels32(pixels);
                texture.Apply();
                File.WriteAllBytes(path, texture.EncodeToPNG());
                Object.DestroyImmediate(texture);
                AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
            }

            return AssetDatabase.LoadAssetAtPath<Sprite>(path);
        }
    }
}

