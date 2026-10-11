/* === ChurrOS Calamares slideshow ===
 *
 * slideshowAPI 2: onActivate / onLeave on the root object.
 * Only QtQuick + calamares.slideshow — no Controls/Layouts.
 * Presentation is a bare Item (no fill). Rectangle is not a Slide
 * (no isSlide), so it stays behind as the dark background.
 */

import QtQuick 2.0;
import calamares.slideshow 1.0;

Presentation
{
    id: presentation

    titleColor: "#F5F5F5"
    textColor: "#A8A8A8"
    fontFamily: "Inter"

    function nextSlide() {
        presentation.goToNextSlide();
    }

    Rectangle {
        anchors.fill: parent
        color: "#0F0F10"
        z: -1
    }

    Timer {
        id: advanceTimer
        interval: 5500
        running: presentation.activatedInCalamares
        repeat: true
        onTriggered: nextSlide()
    }

    Slide {
        Image {
            id: logo
            source: "logo.svg"
            width: 112
            height: 112
            fillMode: Image.PreserveAspectFit
            anchors.centerIn: parent
            anchors.verticalCenterOffset: -48
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: logo.bottom
            anchors.topMargin: 18
            text: "ChurrOS"
            color: "#F5F5F5"
            font.family: "Inter"
            font.pixelSize: 36
            font.bold: true
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: logo.bottom
            anchors.topMargin: 62
            text: qsTr("Arch. @EDITION@. GTK4.")
            color: "#A8A8A8"
            font.family: "Inter"
            font.pixelSize: 15
        }
        Rectangle {
            width: 40
            height: 3
            radius: 2
            color: "#F97316"
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 40
        }
    }

    Slide {
        title: qsTr("Escritorio propio")
        centeredText: qsTr("Welcome, Ajustes y Centro de control\nen GTK4 + Libadwaita.")
    }

    Slide {
        title: qsTr("Escritorios")
        centeredText: qsTr("Niri, XFCE y KDE Plasma,\ncon la misma identidad.")
    }

    Slide {
        title: qsTr("Naranja ChurrOS")
        centeredText: qsTr("La misma paleta en el instalador,\nlas apps y el sitio.")
    }

    Slide {
        title: qsTr("Audio con PipeWire")
        centeredText: qsTr("Baja latencia y enrutamiento flexible\nlisto desde el live.")
    }

    Slide {
        title: qsTr("Listo para crear")
        centeredText: qsTr("Rust, Python, C y Go en un Arch\nque se siente como distro propia.")
    }

    function onActivate() {
        presentation.currentSlide = 0;
    }

    function onLeave() {
    }
}
