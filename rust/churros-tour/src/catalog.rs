//! One catalogue shared by presets, individual selection and the installation plan.
use std::collections::BTreeSet;

pub type Category = (
    &'static str,
    &'static str,
    &'static [(&'static str, &'static str)],
);

pub const CATEGORIES: &[Category] = &[
    (
        "Navegadores Web",
        "Explora internet de forma rápida y segura",
        &[
            ("google-chrome", "Google Chrome"),
            ("brave-bin", "Brave Browser"),
            ("firefox", "Mozilla Firefox"),
            ("tor-browser", "Tor Browser"),
        ],
    ),
    (
        "Ofimática y Productividad",
        "Herramientas para documentos y organización",
        &[
            ("libreoffice-fresh", "LibreOffice (Suite Libre)"),
            ("onlyoffice-bin", "OnlyOffice (Suite Moderna)"),
            ("obsidian", "Obsidian (Notas y conocimiento)"),
            ("notion-app-electron", "Notion (Workspace)"),
            ("ttf-ms-fonts", "Fuentes de Microsoft"),
            ("hunspell-es_es", "Diccionario en Español"),
        ],
    ),
    (
        "Gaming",
        "Steam, Lutris, optimizadores y comunicación",
        &[
            ("steam", "Steam"),
            ("lutris", "Lutris (Gestor de juegos)"),
            ("heroic-games-launcher-bin", "Heroic (Lanzador Epic/GOG)"),
            ("wine", "Wine (Compatibilidad con Windows)"),
            ("gamemode", "GameMode (Optimizador de rendimiento)"),
            ("mangohud", "MangoHud (FPS Overlay)"),
            ("discord", "Discord (Chat y Voz)"),
        ],
    ),
    (
        "Desarrollo y Programación",
        "Lenguajes, contenedores y editores de código",
        &[
            ("visual-studio-code-bin", "Visual Studio Code"),
            ("neovim", "Neovim"),
            ("git", "Git (Control de versiones)"),
            ("docker", "Docker (Contenedores)"),
            ("docker-compose", "Docker Compose"),
            ("nodejs", "Node.js"),
            ("npm", "NPM (Gestor de paquetes)"),
            ("postman-bin", "Postman (Testing de APIs)"),
        ],
    ),
    (
        "Multimedia y Edición",
        "Producción de foto, video y audio",
        &[
            ("vlc", "VLC (Reproductor de medios)"),
            ("obs-studio", "OBS Studio (Streaming y grabación)"),
            ("gimp", "GIMP (Edición de imágenes)"),
            ("kdenlive", "Kdenlive (Edición de video)"),
            ("audacity", "Audacity (Edición de audio)"),
            ("blender", "Blender (Modelado 3D)"),
        ],
    ),
    (
        "Herramientas del Sistema",
        "Monitoreo, respaldos y utilidades",
        &[
            ("btop", "Btop (Monitor de recursos)"),
            ("gparted", "GParted (Gestor de particiones)"),
            ("timeshift", "Timeshift (Copias de seguridad del sistema)"),
            ("flameshot", "Flameshot (Capturas de pantalla avanzadas)"),
            ("qdirstat", "QDirStat (Análisis visual de almacenamiento)"),
            ("unrar", "Unrar (Soporte para archivos .rar)"),
        ],
    ),
];

// The four original presets from d6b9dab. Custom selection retains all 37 apps
// introduced in a6743a0, including apps that do not belong to a preset.
pub const PROFILE_NAMES: &[&str] = &[
    "Personalizado",
    "Ofimática",
    "Gaming",
    "Programación",
    "Multimedia",
];
pub const PRESETS: &[&[&str]] = &[
    &[],
    &["libreoffice-fresh", "ttf-ms-fonts", "hunspell-es_es"],
    &[
        "steam",
        "lutris",
        "wine",
        "heroic-games-launcher-bin",
        "gamemode",
    ],
    &["visual-studio-code-bin", "git", "docker", "docker-compose"],
    &["vlc", "obs-studio", "gimp"],
];

#[derive(Default)]
pub struct Selection(BTreeSet<String>);

impl Selection {
    pub fn set(&mut self, package: &str, active: bool) {
        if !CATEGORIES
            .iter()
            .any(|(_, _, apps)| apps.iter().any(|(id, _)| *id == package))
        {
            return;
        }
        if active {
            self.0.insert(package.to_owned());
        } else {
            self.0.remove(package);
        }
    }

    pub fn packages(&self) -> Vec<String> {
        self.0.iter().cloned().collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn complete_catalogue_has_no_duplicates_and_covers_original_presets() {
        let ids: Vec<_> = CATEGORIES
            .iter()
            .flat_map(|(_, _, apps)| apps.iter().map(|(id, _)| *id))
            .collect();
        assert_eq!(ids.len(), 37);
        assert_eq!(ids.iter().collect::<BTreeSet<_>>().len(), 37);
        assert_eq!(PROFILE_NAMES.len(), PRESETS.len());
        for preset in PRESETS {
            assert!(preset.iter().all(|id| ids.contains(id)));
        }
    }

    #[test]
    fn every_custom_app_can_be_selected_and_deselected_without_duplicates() {
        let mut selection = Selection::default();
        for (_, _, apps) in CATEGORIES {
            for (id, _) in *apps {
                selection.set(id, true);
                selection.set(id, true);
            }
        }
        assert_eq!(selection.packages().len(), 37);
        selection.set("not-in-catalogue; echo injected", true);
        assert_eq!(selection.packages().len(), 37);
        for (_, _, apps) in CATEGORIES {
            for (id, _) in *apps {
                selection.set(id, false);
            }
        }
        assert!(selection.packages().is_empty());
    }
}
