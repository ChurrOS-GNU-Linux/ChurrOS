// ==========================================
// nested — acceso y escritura en objetos JSON anidados sin panic
//
// Vive aquí, y no en churros-settings, porque es la lógica que decidía si la
// app abortaba o no, y así se puede probar sin GTK.
//
// Contexto (auditoría, issue R3): los setters hacían
// `cfg.as_object_mut().unwrap().entry("logo").or_insert_with(json!({}))` y
// después `logo.as_object_mut().unwrap()`. Con un config.jsonc de raíz no
// objeto (por ejemplo `[]`) o con `"logo": "texto"` el unwrap devolvía None y,
// con panic = "abort" en release, mataba la app entera.
// ==========================================

use serde_json::{Map, Value, json};

/// Un valor que se puede usar como objeto de configuración.
///
/// Si la raíz no es un objeto, devuelve uno vacío: leer un config corrupto no
/// puede tumbar la app, y sobrescribirlo con la clave que el usuario acaba de
/// cambiar es preferible a abortar.
pub fn as_object(value: Value) -> Value {
    if value.is_object() { value } else { json!({}) }
}

/// Objeto en la ruta de claves `path`, creándolo si falta o si lo que hay no
/// es un objeto.
///
/// `object_at(&mut cfg, &[])` devuelve la raíz. Con `&["logo"]` devuelve el
/// objeto `logo`, sustituyendo un `"logo": "texto"` anterior, que es lo que
/// hacía abortar a `as_object_mut().unwrap()`.
pub fn object_at<'a>(cfg: &'a mut Value, path: &[&str]) -> &'a mut Map<String, Value> {
    if !cfg.is_object() {
        *cfg = json!({});
    }
    let mut current = cfg.as_object_mut().expect("se acaba de asegurar un objeto");
    for (i, key) in path.iter().enumerate() {
        if !current.get(*key).is_some_and(Value::is_object) {
            current.insert((*key).to_string(), json!({}));
        }
        let next = current
            .get_mut(*key)
            .and_then(Value::as_object_mut)
            .expect("se acaba de insertar un objeto");
        if i + 1 == path.len() {
            return next;
        }
        current = next;
    }
    current
}

#[cfg(test)]
mod tests {
    use super::*;

    /// El caso de R3: raíz `[]` hacía `as_object_mut().unwrap()` -> panic.
    #[test]
    fn root_that_is_not_an_object_becomes_empty() {
        for raw in ["[]", "\"texto\"", "5", "null", "true"] {
            let parsed: Value = serde_json::from_str(raw).unwrap();
            assert!(
                as_object(parsed).is_object(),
                "una raíz {raw} tiene que normalizarse a objeto"
            );
        }
        assert!(as_object(json!({"a": 1})).is_object());
    }

    /// Segundo disparador de R3: `"logo": "texto"` en vez de un objeto.
    #[test]
    fn object_at_replaces_a_key_that_is_not_an_object() {
        let mut cfg = json!({"logo": "texto"});
        let logo = object_at(&mut cfg, &["logo"]);
        logo.insert("type".to_string(), json!("builtin"));
        assert_eq!(cfg["logo"]["type"], json!("builtin"));
    }

    #[test]
    fn object_at_creates_missing_levels() {
        let mut cfg = json!({});
        let key = object_at(&mut cfg, &["display", "key"]);
        key.insert("width".to_string(), json!(20));
        assert_eq!(cfg["display"]["key"]["width"], json!(20));
    }

    #[test]
    fn object_at_keeps_sibling_keys() {
        let mut cfg = json!({"display": {"separator": "x", "key": {"width": 12}}});
        object_at(&mut cfg, &["display", "key"]).insert("width".to_string(), json!(40));
        assert_eq!(cfg["display"]["separator"], json!("x"));
        assert_eq!(cfg["display"]["key"]["width"], json!(40));
    }

    #[test]
    fn object_at_with_empty_path_returns_the_root() {
        let mut cfg = json!({"modules": []});
        object_at(&mut cfg, &[]).insert("x".to_string(), json!(1));
        assert_eq!(cfg["x"], json!(1));
        assert!(cfg["modules"].is_array());
    }

    /// Una raíz no objeto también tiene que poder escribirse.
    #[test]
    fn object_at_recovers_from_a_non_object_root() {
        let mut cfg = json!([1, 2, 3]);
        object_at(&mut cfg, &["logo"]).insert("type".to_string(), json!("none"));
        assert_eq!(cfg["logo"]["type"], json!("none"));
    }
}
