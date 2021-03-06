/*global define, google */
define(['modules/depotDistance'], function (depotDistance) {

    $(function () {
        if (window.google) {
            var initialize = function () {
                var mapOptions = {
                    zoom: 14,
                    center: new google.maps.LatLng(47.4099048, 8.3823588),
                    mapTypeId: google.maps.MapTypeId.ROADMAP
                };

                var map = new google.maps.Map(document.getElementById('map-canvas'), mapOptions);

                depotDistance.createDepotOnMap(map, 'Fondlihof - Dietikon', 'Spreitenbacherstrasse 35', '8953', 'Dietikon', 47.4099048, 8.3823588);
            };

            google.maps.event.addDomListener(window, 'load', initialize);
        }
    });
});