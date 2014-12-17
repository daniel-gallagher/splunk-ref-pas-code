require([
    "splunkjs/ready!",
    "splunkjs/mvc/simplexml/ready!",
    "jquery",
    "underscore"
], function(
    mvc,
    ignored,
    $,
    _
) {
    var USER_INFO_BOX_TEMPLATE = _.template(
        '<div class="user_info_box">' +
        // '    <div class="user_name"><%= user_name %></div>' +
        '    <div class="user_fullname"><%= user_fullname %></div>' +
        '    <div class="user_email"><%= user_email %></div>'+
        '    <div class="user_phone"><%= user_phone %></div>' +
        '    <div class="company_name"><%= company_name %></div>'+
        '    <div class="user_role"><%= user_role %></div>'+
        '    <div class="company_address"><%= company_address %></div>' +
        '    <div class="company_phone"><%= company_phone %></div>' +
        '    <div class="user_image"><%= user_image %></div>' +
        '</div>');
    
    var view = $("#user_info");
    view.html("Getting user info...");
    var userInfoSearch = mvc.Components.get("user_info_search");
    
    userInfoSearch.data("results", {
        // HACK: By default, no "data" event is fired when no results are
        //       found. Override so that it does fire in this case.
        condition: function(manager, job) {
            return (job.properties() || {}).isDone;
        }
    }).on("data", function(resultsModel) {
        var rows = resultsModel.data().rows;
        if (rows.length === 0) {
            view.html("No user information found.");
        } else {
            view.html("");
            _.each(rows, function(row) {
                var companyAddress = row[0];
                var companyName = row[1];
                var companyPhone = row[2];
                var userEmail = row[3];
                var userFullName = row[4];
                var userImage = row[5];
                // var userName = row[6];
                var userPhone = row[7];
                var userRole = row[8];
                view.append($(USER_INFO_BOX_TEMPLATE({
                    // user_name: userName,
                    user_fullname: userFullName,
                    user_email: userEmail,
                    user_phone: userPhone,
                    company_name: companyName,
                    user_role: userRole,
                    company_address: companyAddress,
                    company_phone: companyPhone,
                    user_image: userImage
                })));
            });
        }
    });
 });